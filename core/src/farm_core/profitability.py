"""The deterministic profitability engine: combines Phase 1's resolved field
identity with Phase 2's reconciled data into one profit-per-lineage-per-season
table, then answers the two questions v1 exists to answer -- "which fields
made money" and "was this field a bad field or a bad year" -- with plain
arithmetic and a documented statistical rule, never a guess.

Revenue always comes from scale tickets (the authoritative bushel source per
Phase 2's reconciliation), never the yield monitor. Costs come from the
cost ledger, resolved through the naming-drift alias table first.
"""

from __future__ import annotations

import dataclasses
import statistics

import duckdb

from .field_identity import FieldIdentityResolution

LOSS_RATE_BAD_FIELD_THRESHOLD = 0.5  # >= this fraction of loss seasons -> chronically bad field
OUTLIER_MAD_MULTIPLIER = 2.0  # season profit this many MADs below the field's median -> bad year


@dataclasses.dataclass(frozen=True)
class ProfitRecord:
    canonical_id: str
    display_name: str
    season: int
    crop: str
    acres: float
    revenue: float
    total_cost: float
    profit: float
    profit_per_acre: float


def _resolved_cost_rows(
    con: duckdb.DuckDBPyConnection, alias_map: dict[tuple[int, str], str]
) -> dict[tuple[int, str], dict]:
    rows = con.execute(
        "SELECT season, raw_field_name, seed_cost_per_ac, fertilizer_cost_per_ac, "
        "chemical_cost_per_ac, fuel_cost_per_ac, cash_rent_per_ac FROM cost_ledger_rows"
    ).fetchall()
    out: dict[tuple[int, str], dict] = {}
    for season, raw_name, seed, fert, chem, fuel, rent in rows:
        resolved_name = alias_map.get((season, raw_name), raw_name)
        out[(season, resolved_name)] = {
            "seed_cost_per_ac": seed,
            "fertilizer_cost_per_ac": fert,
            "chemical_cost_per_ac": chem,
            "fuel_cost_per_ac": fuel,
            "cash_rent_per_ac": rent,
        }
    return out


def compute_profitability(
    con: duckdb.DuckDBPyConnection,
    identity: FieldIdentityResolution,
    alias_map: dict[tuple[int, str], str],
) -> dict[tuple[str, int], ProfitRecord]:
    cost_by_season_name = _resolved_cost_rows(con, alias_map)
    records: dict[tuple[str, int], ProfitRecord] = {}

    for canonical_id, lineage in identity.lineages.items():
        for season in lineage.active_seasons:
            display_name = lineage.display_name_by_season[season]

            boundary = con.execute(
                "SELECT acres, crop FROM boundary_fields WHERE field_name = ? AND season = ?",
                [display_name, season],
            ).fetchone()
            if boundary is None:
                continue
            acres, crop = boundary

            revenue = (
                con.execute(
                    "SELECT SUM(net_bushels * price_per_bu) FROM scale_ticket_loads "
                    "WHERE field_name = ? AND season = ?",
                    [display_name, season],
                ).fetchone()[0]
                or 0.0
            )

            cost_row = cost_by_season_name.get((season, display_name))
            if cost_row is None:
                continue
            total_cost = (
                sum(
                    cost_row[k]
                    for k in (
                        "seed_cost_per_ac",
                        "fertilizer_cost_per_ac",
                        "chemical_cost_per_ac",
                        "fuel_cost_per_ac",
                        "cash_rent_per_ac",
                    )
                )
                * acres
            )

            profit = revenue - total_cost
            records[(canonical_id, season)] = ProfitRecord(
                canonical_id=canonical_id,
                display_name=display_name,
                season=season,
                crop=crop,
                acres=acres,
                revenue=round(revenue, 2),
                total_cost=round(total_cost, 2),
                profit=round(profit, 2),
                profit_per_acre=round(profit / acres, 2) if acres else 0.0,
            )

    return records


def which_fields_made_money(
    records: dict[tuple[str, int], ProfitRecord], seasons: list[int]
) -> list[dict]:
    """Ranked total profit per canonical lineage across the given seasons.
    Each lineage is reported separately -- a split/merge/rename is never
    silently blended with a different lineage's acres.
    """
    season_set = set(seasons)
    by_lineage: dict[str, list[ProfitRecord]] = {}
    for (canonical_id, season), record in records.items():
        if season in season_set:
            by_lineage.setdefault(canonical_id, []).append(record)

    results = []
    for canonical_id, recs in by_lineage.items():
        recs.sort(key=lambda r: r.season)
        results.append(
            {
                "canonical_id": canonical_id,
                "display_name": recs[-1].display_name,
                "seasons": [r.season for r in recs],
                "total_profit": round(sum(r.profit for r in recs), 2),
                "total_revenue": round(sum(r.revenue for r in recs), 2),
                "total_cost": round(sum(r.total_cost for r in recs), 2),
            }
        )
    results.sort(key=lambda r: r["total_profit"], reverse=True)
    return results


def bad_field_or_bad_year(records: dict[tuple[str, int], ProfitRecord], canonical_id: str) -> dict:
    """Classify a field's profit history: chronically underperforming (bad
    field), a specific outlier season in an otherwise fine history (bad
    year), or neither.

    A field is "bad_field" if it lost money in at least half its seasons --
    that's a pattern, not an incident. Otherwise, a season is "bad_year" if
    its profit is more than OUTLIER_MAD_MULTIPLIER median-absolute-deviations
    below the field's own median -- a robust outlier test that isn't itself
    skewed by the outlier it's looking for.
    """
    field_recs = sorted(
        (r for (cid, _), r in records.items() if cid == canonical_id), key=lambda r: r.season
    )
    if not field_recs:
        return {"canonical_id": canonical_id, "verdict": "no_data", "evidence": {}}

    profits = [r.profit_per_acre for r in field_recs]
    loss_rate = sum(1 for p in profits if p < 0) / len(profits)

    if loss_rate >= LOSS_RATE_BAD_FIELD_THRESHOLD:
        return {
            "canonical_id": canonical_id,
            "verdict": "bad_field",
            "evidence": {
                "loss_rate": round(loss_rate, 2),
                "seasons_with_loss": [r.season for r in field_recs if r.profit_per_acre < 0],
                "num_seasons": len(field_recs),
            },
        }

    median_profit = statistics.median(profits)
    mad = statistics.median(abs(p - median_profit) for p in profits)
    outlier_seasons = []
    if mad > 0:
        for r in field_recs:
            if (median_profit - r.profit_per_acre) / mad > OUTLIER_MAD_MULTIPLIER:
                outlier_seasons.append(r.season)

    if outlier_seasons:
        return {
            "canonical_id": canonical_id,
            "verdict": "bad_year",
            "evidence": {
                "outlier_seasons": outlier_seasons,
                "median_profit_per_acre": round(median_profit, 2),
                "num_seasons": len(field_recs),
            },
        }

    return {
        "canonical_id": canonical_id,
        "verdict": "consistently_profitable",
        "evidence": {
            "median_profit_per_acre": round(median_profit, 2),
            "loss_rate": round(loss_rate, 2),
            "num_seasons": len(field_recs),
        },
    }
