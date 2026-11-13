"""Season weather, field soil and as-applied inputs, as verified lookups.

The weather-history and as-applied servers are thin wrappers around these
functions. Everything a grower-facing answer states is computed here, in
plain Python against the farm snapshot, so the narrator's template sentence
can restate it and the grounding check can find every number it uses.

Nothing here explains a yield or a loss. These are records: how much rain
fell, how much water a field's soil holds, what was applied. Saying *why*
a season went badly stays with farm_core.expectation (report-export).
"""

from __future__ import annotations

from typing import Any

from .expectation import CROP_WATER_NEED_MM, HEAT_STRESS_THRESHOLD_C
from .pipeline import FarmSnapshot
from .reconciliation import UAN32_LB_N_PER_GAL


class LookupRefused(Exception):
    """A structured refusal: the tool returns {"error": reason, "code": code}."""

    def __init__(self, reason: str, code: str):
        self.reason = reason
        self.code = code
        super().__init__(reason)


# -- weather ----------------------------------------------------------------


def _season_weather_totals(snap: FarmSnapshot) -> dict[int, tuple[float, int]]:
    rows = snap.con.execute(
        "SELECT season, SUM(precip_mm), SUM(CASE WHEN temp_max_c > ? THEN 1 ELSE 0 END) "
        "FROM weather_daily GROUP BY season ORDER BY season",
        [HEAT_STRESS_THRESHOLD_C],
    ).fetchall()
    return {int(s): (float(p), int(h)) for s, p, h in rows if p is not None}


def season_weather_summary(snap: FarmSnapshot, season: int) -> dict[str, Any]:
    """One season's rain and heat, set against every season on record."""
    if season not in snap.seasons:
        raise LookupRefused(
            f"unknown season {season}; known seasons are {snap.seasons}", "invalid_input"
        )
    totals = _season_weather_totals(snap)
    if season not in totals:
        raise LookupRefused(f"no weather coverage for season {season}", "not_found")

    precip, heat_days = totals[season]
    precip = round(precip, 1)
    n = len(totals)
    avg_precip = round(sum(p for p, _ in totals.values()) / n, 1)
    avg_heat = round(sum(h for _, h in totals.values()) / n, 1)
    # 1 = the driest season on record, n = the wettest.
    rank_driest = 1 + sum(1 for p, _ in totals.values() if round(p, 1) < precip)
    pct = round((precip - avg_precip) / avg_precip * 100) if avg_precip else 0
    return {
        "season": season,
        "total_precip_mm": precip,
        "farm_average_precip_mm": avg_precip,
        "pct_vs_farm_average": int(pct),
        "num_seasons_compared": n,
        "precip_rank_driest": rank_driest,
        "crop_water_need_mm": CROP_WATER_NEED_MM,
        "precip_short_of_need_mm": round(max(0.0, CROP_WATER_NEED_MM - precip), 1),
        "heat_stress_days": heat_days,
        "farm_average_heat_stress_days": avg_heat,
        "heat_stress_threshold_c": HEAT_STRESS_THRESHOLD_C,
    }


# -- soil -------------------------------------------------------------------


def _current_field_names(snap: FarmSnapshot) -> list[str]:
    latest = max(snap.seasons)
    return sorted(
        lineage.display_name_by_season[latest]
        for lineage in snap.identity.lineages.values()
        if latest in lineage.display_name_by_season
    )


def field_soil_summary(snap: FarmSnapshot, field_name: str) -> dict[str, Any]:
    """A field's soil available-water capacity, and the farm's range today."""
    row = snap.con.execute(
        "SELECT field_name, awc_in FROM soil_awc WHERE field_name = ?", [field_name]
    ).fetchone()
    if row is None:
        canonical_id = snap.canonical_id_for_name(field_name)
        if canonical_id is not None:
            lineage = snap.identity.lineages[canonical_id]
            current_name = lineage.display_name_by_season[max(lineage.active_seasons)]
            row = snap.con.execute(
                "SELECT field_name, awc_in FROM soil_awc WHERE field_name = ?", [current_name]
            ).fetchone()
    if row is None:
        raise LookupRefused(
            f"{field_name!r} does not resolve to a field with recorded soil data", "not_found"
        )

    current = _current_field_names(snap)
    awc_rows = snap.con.execute(
        "SELECT field_name, awc_in FROM soil_awc WHERE field_name IN "
        f"({', '.join('?' for _ in current)})",
        current,
    ).fetchall()
    by_name = {name: float(awc) for name, awc in awc_rows}
    min_name = min(by_name, key=lambda k: (by_name[k], k))
    max_name = max(by_name, key=lambda k: (by_name[k], k))
    return {
        "field_name": row[0],
        "asked_name": field_name,
        "awc_in": float(row[1]),
        "farm_min_awc_in": by_name[min_name],
        "min_field_name": min_name,
        "farm_max_awc_in": by_name[max_name],
        "max_field_name": max_name,
        "num_current_fields": len(by_name),
    }


# -- as-applied -------------------------------------------------------------

_INPUT_ORDER = ("seed", "nitrogen", "phosphorus", "potassium", "herbicide")
_UNIT_LABELS = {
    "lb_N/ac": "lb N/ac",
    "lb_P2O5/ac": "lb P2O5/ac",
    "lb_K2O/ac": "lb K2O/ac",
}


def _input_kind(product: str) -> str:
    p = product.lower()
    if p.startswith("seed"):
        return "seed"
    if p.startswith(("anhydrous", "uan")):
        return "nitrogen"
    if p.startswith("map"):
        return "phosphorus"
    if p.startswith("potash"):
        return "potassium"
    return "herbicide"


def _logged_seasons(snap: FarmSnapshot) -> list[int]:
    return [
        int(r[0])
        for r in snap.con.execute(
            "SELECT DISTINCT season FROM as_applied_events ORDER BY season"
        ).fetchall()
    ]


def _crop(snap: FarmSnapshot, name: str, season: int) -> str | None:
    row = snap.con.execute(
        "SELECT crop FROM boundary_fields WHERE field_name = ? AND season = ?", [name, season]
    ).fetchone()
    return str(row[0]) if row else None


def _nitrogen_entry(product: str, rate: float, rate_unit: str) -> dict[str, Any]:
    """Every nitrogen rate in lb N/ac. A gal/ac reading is gallons of UAN 32%
    product, so it is converted -- the as-logged number is kept beside it.
    """
    if rate_unit == "gal/ac":
        lb = round(rate * UAN32_LB_N_PER_GAL, 1)
        converted = True
    else:
        lb = round(rate, 1)
        converted = False
    return {
        "input": "nitrogen",
        "product": product,
        "rate": lb,
        "unit": "lb N/ac",
        "as_logged_rate": rate,
        "as_logged_unit": rate_unit,
        "converted": converted,
    }


def _resolve_lineage(snap: FarmSnapshot, field_name: str):
    canonical_id = snap.canonical_id_for_name(field_name)
    if canonical_id is None:
        raise LookupRefused(f"{field_name!r} does not resolve to a known field", "not_found")
    return snap.identity.lineages[canonical_id]


def applied_inputs(snap: FarmSnapshot, field_name: str, season: int) -> dict[str, Any]:
    """What the as-applied log shows for one field and season, N in lb N/ac."""
    if season not in snap.seasons:
        raise LookupRefused(
            f"unknown season {season}; known seasons are {snap.seasons}", "invalid_input"
        )
    lineage = _resolve_lineage(snap, field_name)
    name = lineage.display_name_by_season.get(season)
    if name is None:
        raise LookupRefused(f"{field_name!r} was not a field in season {season}", "not_found")

    logged = _logged_seasons(snap)
    result: dict[str, Any] = {
        "field_name": name,
        "asked_name": field_name,
        "season": season,
        "crop": _crop(snap, name, season),
        "logged": season in logged,
        "logged_seasons": logged,
        "applied_inputs": [],
        "nitrogen_lb_n_ac": None,
        "uan32_lb_n_per_gal": UAN32_LB_N_PER_GAL,
    }
    if season not in logged:
        return result

    rows = snap.con.execute(
        "SELECT product, rate, rate_unit FROM as_applied_events "
        "WHERE field_name = ? AND season = ? ORDER BY timestamp",
        [name, season],
    ).fetchall()
    entries = []
    for product, rate, unit in rows:
        kind = _input_kind(product)
        if kind == "nitrogen":
            entries.append(_nitrogen_entry(product, float(rate), unit))
        else:
            entries.append(
                {
                    "input": kind,
                    "product": product,
                    "rate": float(rate),
                    "unit": _UNIT_LABELS.get(unit, unit),
                    "as_logged_rate": float(rate),
                    "as_logged_unit": unit,
                    "converted": False,
                }
            )
    entries.sort(key=lambda e: _INPUT_ORDER.index(e["input"]))
    result["applied_inputs"] = entries
    n = [e for e in entries if e["input"] == "nitrogen"]
    result["nitrogen_lb_n_ac"] = n[0]["rate"] if n else None
    return result


def nitrogen_history(snap: FarmSnapshot, field_name: str) -> dict[str, Any]:
    """Nitrogen in lb N/ac for every logged season of one field, by crop."""
    lineage = _resolve_lineage(snap, field_name)
    logged = _logged_seasons(snap)
    latest_name = lineage.display_name_by_season[max(lineage.active_seasons)]

    rows: list[dict[str, Any]] = []
    for season in logged:
        name = lineage.display_name_by_season.get(season)
        if name is None:
            continue
        event = snap.con.execute(
            "SELECT product, rate, rate_unit FROM as_applied_events "
            "WHERE field_name = ? AND season = ? "
            "AND (product LIKE 'Anhydrous%' OR product LIKE 'UAN%') ORDER BY timestamp",
            [name, season],
        ).fetchone()
        if event is None:
            continue
        entry = _nitrogen_entry(event[0], float(event[1]), event[2])
        rows.append(
            {
                "season": season,
                "field_name": name,
                "crop": _crop(snap, name, season),
                "product": entry["product"],
                "n_lb_n_ac": entry["rate"],
                "as_logged_rate": entry["as_logged_rate"],
                "as_logged_unit": entry["as_logged_unit"],
                "converted": entry["converted"],
            }
        )
    if not rows:
        raise LookupRefused(
            f"no as-applied nitrogen is logged for {field_name!r}", "not_found"
        )

    by_crop: dict[str, dict[str, Any]] = {}
    for crop in sorted({r["crop"] for r in rows if r["crop"]}):
        crop_rows = [r for r in rows if r["crop"] == crop]
        lo = min(crop_rows, key=lambda r: (r["n_lb_n_ac"], r["season"]))
        hi = max(crop_rows, key=lambda r: (r["n_lb_n_ac"], -r["season"]))
        by_crop[crop] = {
            "num_seasons": len(crop_rows),
            "min_lb_n_ac": lo["n_lb_n_ac"],
            "min_season": lo["season"],
            "max_lb_n_ac": hi["n_lb_n_ac"],
            "max_season": hi["season"],
            "spread_lb_n_ac": round(hi["n_lb_n_ac"] - lo["n_lb_n_ac"], 1),
        }
    return {
        "field_name": latest_name,
        "asked_name": field_name,
        "nitrogen_by_season": rows,
        "nitrogen_by_crop": by_crop,
        "logs_start_season": min(logged),
        "uan32_lb_n_per_gal": UAN32_LB_N_PER_GAL,
    }
