"""Reconcile independent data sources. Where they disagree is a feature, not
an error to paper over -- every function here returns both figures and a
neutral flag, never an assertion that one side is wrong. Deciding which
figure is authoritative for the final profitability number is Phase 3's job,
not this module's.
"""

from __future__ import annotations

import dataclasses

import duckdb

CALIBRATION_THRESHOLD_PCT = 0.03
COVERAGE_GRID_BINS = 8
COVERAGE_MIN_AVG_POINTS_PER_BIN = 3.0
COVERAGE_EDGE_DENSITY_RATIO = 0.35  # edge bin flagged if under this fraction of interior average

UAN32_LB_N_PER_GAL = 3.5392  # must match generator/src/farm_data_gen/as_applied.py
SEEDS_PER_UNIT_CORN = 80_000  # must match generator/src/farm_data_gen/config.py
SEEDS_PER_UNIT_SOYBEAN = 140_000
OUTLIER_THRESHOLD_PCT = 0.25


@dataclasses.dataclass(frozen=True)
class YieldReconciliation:
    field_name: str
    season: int
    scale_total_bu: float
    monitor_total_bu: float | None
    pct_diff: float | None
    totals_discrepancy: bool
    coverage_gap_bins: int | None
    coverage_gap_flagged: bool
    note: str


def _monitor_total_bu(con: duckdb.DuckDBPyConnection, field_name: str, season: int) -> float | None:
    row = con.execute(
        "SELECT AVG(dry_bu_ac) FROM yield_monitor_points WHERE field_name = ? AND season = ?",
        [field_name, season],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    acres_row = con.execute(
        "SELECT acres FROM boundary_fields WHERE field_name = ? AND season = ?",
        [field_name, season],
    ).fetchone()
    if acres_row is None:
        return None
    return row[0] * acres_row[0]


def _check_spatial_coverage(
    con: duckdb.DuckDBPyConnection, field_name: str, season: int
) -> int | None:
    """Bins yield-monitor points along longitude and looks for a sharp density
    drop at either edge of the field -- the shape a GPS-dropout gap leaves.
    A real gap doesn't necessarily line up with a bin boundary, so this
    compares each edge bin's density against the interior average rather than
    requiring a fully empty bin. Returns the number of anomalously sparse edge
    bins (1 or 2), or None if coverage looks uniform (or there's no monitor
    data at all).
    """
    bbox = con.execute(
        "SELECT min_lon, max_lon FROM boundary_fields WHERE field_name = ? AND season = ?",
        [field_name, season],
    ).fetchone()
    if bbox is None:
        return None
    min_lon, max_lon = bbox

    lons = [
        r[0]
        for r in con.execute(
            "SELECT lon FROM yield_monitor_points WHERE field_name = ? AND season = ?",
            [field_name, season],
        ).fetchall()
    ]
    if not lons:
        return None

    bin_width = (max_lon - min_lon) / COVERAGE_GRID_BINS
    counts = [0] * COVERAGE_GRID_BINS
    for lon in lons:
        idx = min(COVERAGE_GRID_BINS - 1, max(0, int((lon - min_lon) / bin_width)))
        counts[idx] += 1

    interior = counts[1:-1]
    if not interior or sum(interior) / len(interior) < COVERAGE_MIN_AVG_POINTS_PER_BIN:
        return None  # too sparse overall to distinguish a real gap from noise
    interior_avg = sum(interior) / len(interior)
    threshold = interior_avg * COVERAGE_EDGE_DENSITY_RATIO

    gap_bins = sum(1 for edge in (counts[0], counts[-1]) if edge < threshold)
    return gap_bins if gap_bins > 0 else None


def reconcile_yield_vs_scale(con: duckdb.DuckDBPyConnection) -> list[YieldReconciliation]:
    pairs = con.execute(
        "SELECT DISTINCT field_name, season FROM scale_ticket_loads ORDER BY season, field_name"
    ).fetchall()

    results = []
    for field_name, season in pairs:
        scale_total = con.execute(
            "SELECT SUM(net_bushels) FROM scale_ticket_loads WHERE field_name = ? AND season = ?",
            [field_name, season],
        ).fetchone()[0]

        monitor_total = _monitor_total_bu(con, field_name, season)
        pct_diff = None
        totals_discrepancy = False
        if monitor_total is not None and scale_total:
            pct_diff = (monitor_total - scale_total) / scale_total
            totals_discrepancy = abs(pct_diff) > CALIBRATION_THRESHOLD_PCT

        gap_bins = _check_spatial_coverage(con, field_name, season)

        if monitor_total is None:
            note = "No yield monitor data this season; scale tickets are the sole yield source."
        elif totals_discrepancy:
            note = (
                f"Yield monitor and scale ticket totals differ by {pct_diff * 100:+.1f}% "
                f"on {field_name} in {season} -- these two do not match, want to look?"
            )
        elif gap_bins:
            note = (
                f"Yield monitor coverage for {field_name} in {season} has a gap "
                f"({gap_bins}/{COVERAGE_GRID_BINS} bins empty at one edge) despite totals "
                "reconciling normally -- a totals-only check would miss this."
            )
        else:
            note = "Yield monitor and scale ticket totals reconcile within tolerance."

        results.append(
            YieldReconciliation(
                field_name=field_name,
                season=season,
                scale_total_bu=scale_total,
                monitor_total_bu=monitor_total,
                pct_diff=pct_diff,
                totals_discrepancy=totals_discrepancy,
                coverage_gap_bins=gap_bins,
                coverage_gap_flagged=gap_bins is not None,
                note=note,
            )
        )

    return results


@dataclasses.dataclass(frozen=True)
class CostReconciliation:
    field_name: str
    season: int
    line_item: str  # "seed" | "fertilizer"
    ledger_cost_per_ac: float
    as_applied_derived_cost_per_ac: float | None
    pct_diff: float | None
    outlier_flagged: bool
    note: str


def _seed_cost_per_ac(rate_kseeds_ac: float, crop: str, unit_prices_row: dict) -> float:
    if crop == "corn":
        return (rate_kseeds_ac * 1000 / SEEDS_PER_UNIT_CORN) * unit_prices_row[
            "seed_corn_price_per_unit"
        ]
    return (rate_kseeds_ac * 1000 / SEEDS_PER_UNIT_SOYBEAN) * unit_prices_row[
        "seed_soybean_price_per_unit"
    ]


def _n_lb_per_ac(rate: float, rate_unit: str) -> float:
    if rate_unit == "lb_N/ac":
        return rate
    if rate_unit == "gal/ac":
        return rate * UAN32_LB_N_PER_GAL
    raise ValueError(f"Unrecognized N rate unit: {rate_unit!r}")


def reconcile_cost_ledger_vs_as_applied(
    con: duckdb.DuckDBPyConnection, field_name_by_season_and_raw: dict[tuple[int, str], str]
) -> list[CostReconciliation]:
    """Compares the ledger's stated seed and fertilizer $/ac against what the
    as-applied logs plus unit prices imply, for seasons where both exist
    (the last four). Cost-ledger field names are resolved through the
    naming-drift alias table before joining, since the drift field's ledger
    spelling cycles through several variants across exactly this window.
    """
    unit_price_rows = {
        r[0]: {
            "seed_corn_price_per_unit": r[1],
            "seed_soybean_price_per_unit": r[2],
            "n_price_per_lb": r[3],
            "p_price_per_lb": r[4],
            "k_price_per_lb": r[5],
        }
        for r in con.execute(
            "SELECT season, seed_corn_price_per_unit, seed_soybean_price_per_unit, "
            "n_price_per_lb, p_price_per_lb, k_price_per_lb FROM unit_prices"
        ).fetchall()
    }

    ledger_rows = con.execute(
        "SELECT season, raw_field_name, crop, seed_cost_per_ac, fertilizer_cost_per_ac "
        "FROM cost_ledger_rows "
        "WHERE season IN (SELECT DISTINCT season FROM as_applied_events)"
    ).fetchall()

    results: list[CostReconciliation] = []
    for season, raw_name, crop, ledger_seed, ledger_fert in ledger_rows:
        field_name = field_name_by_season_and_raw.get((season, raw_name), raw_name)
        unit_prices_row = unit_price_rows.get(season)
        if unit_prices_row is None:
            continue

        events = con.execute(
            "SELECT product, rate, rate_unit FROM as_applied_events "
            "WHERE field_name = ? AND season = ?",
            [field_name, season],
        ).fetchall()
        by_product = {p: (rate, unit) for p, rate, unit in events}

        seed_event = next(
            ((rate, unit) for p, (rate, unit) in by_product.items() if p.startswith("Seed")),
            None,
        )
        n_event = next(
            (
                (rate, unit)
                for p, (rate, unit) in by_product.items()
                if p.startswith(("Anhydrous", "UAN"))
            ),
            None,
        )
        p_event = by_product.get("MAP (11-52-0)")
        k_event = by_product.get("Potash (0-0-60)")

        if seed_event is not None:
            derived_seed = _seed_cost_per_ac(seed_event[0], crop, unit_prices_row)
            seed_diff = (derived_seed - ledger_seed) / ledger_seed if ledger_seed else None
            seed_outlier = seed_diff is not None and abs(seed_diff) > OUTLIER_THRESHOLD_PCT
            results.append(
                CostReconciliation(
                    field_name=field_name,
                    season=season,
                    line_item="seed",
                    ledger_cost_per_ac=ledger_seed,
                    as_applied_derived_cost_per_ac=derived_seed,
                    pct_diff=seed_diff,
                    outlier_flagged=seed_outlier,
                    note=(
                        f"Ledger seed cost (${ledger_seed:.2f}/ac) vs as-applied-derived "
                        f"(${derived_seed:.2f}/ac) differ by "
                        f"{seed_diff * 100:+.1f}% on {field_name} in {season}."
                        if seed_outlier
                        else "Ledger and as-applied-derived seed cost reconcile within tolerance."
                    ),
                )
            )

        if n_event is not None and p_event is not None and k_event is not None:
            n_cost = _n_lb_per_ac(*n_event) * unit_prices_row["n_price_per_lb"]
            p_cost = p_event[0] * unit_prices_row["p_price_per_lb"]
            k_cost = k_event[0] * unit_prices_row["k_price_per_lb"]
            derived_fert = n_cost + p_cost + k_cost
            fert_diff = (derived_fert - ledger_fert) / ledger_fert if ledger_fert else None
            fert_outlier = fert_diff is not None and abs(fert_diff) > OUTLIER_THRESHOLD_PCT
            results.append(
                CostReconciliation(
                    field_name=field_name,
                    season=season,
                    line_item="fertilizer",
                    ledger_cost_per_ac=ledger_fert,
                    as_applied_derived_cost_per_ac=derived_fert,
                    pct_diff=fert_diff,
                    outlier_flagged=fert_outlier,
                    note=(
                        f"Ledger fertilizer cost (${ledger_fert:.2f}/ac) vs as-applied-derived "
                        f"(${derived_fert:.2f}/ac) differ by "
                        f"{fert_diff * 100:+.1f}% on {field_name} in {season}."
                        if fert_outlier
                        else (
                            "Ledger and as-applied-derived fertilizer cost reconcile within "
                            "tolerance."
                        )
                    ),
                )
            )

    return results
