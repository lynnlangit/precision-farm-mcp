"""Central registry of which (field, season) gets which defect, and the stable
defect IDs that ground_truth.json records. This module only decides the
*assignment* -- deterministically, from the seed, in a fixed order so the RNG
draw sequence never depends on iteration order. The actual bytes of each defect
(a shifted CSV total, a merged Excel header, ...) are produced by the writer
module that owns that file format, using the assignment decided here, and that
writer hands back the ground-truth defect record(s) for ground_truth.py to
collect.
"""

from __future__ import annotations

import dataclasses

from . import rng as rng_mod
from .farm import FarmModel
from .field_identity import (
    ALIAS_TIE_FIELD_IDS,
    ALIAS_TIE_MISSPELLING,
    ALIAS_TIE_NAIVE_WRONG_MATCH,
    ALIAS_TIE_SEASON_INDEX,
    BADZONE_FIELD_ID,
    scaled_indices,
)


@dataclasses.dataclass
class DefectPlan:
    no_monitor_seasons: list[int]
    calibration_errors: list[dict]  # {field_id, season, error_pct} (signed)
    missing_swath: dict  # {field_id, season, gap_fraction}
    unit_inconsistency_by_season: dict[int, str]  # season -> "lb_per_ac" | "product_per_ac"
    spreadsheet_mess: dict  # keyed defect assignments, see below
    total_dollars_season: int
    transposed_digit: dict  # {season, field_id, original, transposed}
    bad_zone: dict | None  # {field_id, season, zone_index} or None if the field isn't in the roster


def plan_defects(farm: FarmModel) -> DefectPlan:
    config = farm.config
    seasons = config.seasons

    no_monitor_seasons = [seasons[i] for i in range(config.no_monitor_seasons_count)]

    monitor_eligible_seasons = [s for s in seasons if s not in no_monitor_seasons]
    monitor_fields_by_season = {s: farm.fields_active_in(s) for s in monitor_eligible_seasons}

    calibration_errors: list[dict] = []
    r = rng_mod.derive_rng(config.random_seed, "defects", "calibration")
    chosen_seasons = sorted(
        r.choice(
            monitor_eligible_seasons,
            size=min(config.calibration_error_seasons_count, len(monitor_eligible_seasons)),
            replace=False,
        ).tolist()
    )
    for i, season in enumerate(chosen_seasons):
        fields = monitor_fields_by_season[season]
        field_r = rng_mod.derive_rng(config.random_seed, "defects", "calibration_field", season)
        field_id = str(field_r.choice(sorted(fields)))
        lo, hi = config.calibration_error_pct_range
        pct_r = rng_mod.derive_rng(config.random_seed, "defects", "calibration_pct", season)
        pct = float(pct_r.uniform(lo, hi))
        sign = 1 if i % 2 == 0 else -1  # guarantee both directions occur
        calibration_errors.append({"field_id": field_id, "season": season, "error_pct": sign * pct})

    swath_season = seasons[scaled_indices(config, len(seasons))["missing_swath"]]
    swath_fields = monitor_fields_by_season.get(swath_season, farm.fields_active_in(swath_season))
    swath_r = rng_mod.derive_rng(config.random_seed, "defects", "missing_swath")
    swath_field_id = str(swath_r.choice(sorted(swath_fields)))
    gap_r = rng_mod.derive_rng(config.random_seed, "defects", "missing_swath_gap")
    missing_swath = {
        "field_id": swath_field_id,
        "season": swath_season,
        "gap_fraction": float(gap_r.uniform(0.10, 0.20)),
    }

    unit_inconsistency_by_season = {
        s: ("lb_per_ac" if i % 2 == 0 else "product_per_ac")
        for i, s in enumerate(seasons)
        if i >= config.num_seasons - config.as_applied_seasons_count
    }

    total_dollars_season_index = min(2, len(seasons) - 1)
    total_dollars_season = seasons[total_dollars_season_index]

    transposed_r = rng_mod.derive_rng(config.random_seed, "defects", "transposed_digit")
    transposed_season = seasons[min(6, len(seasons) - 1)]
    transposed_fields = farm.fields_active_in(transposed_season)
    transposed_field_id = str(transposed_r.choice(sorted(transposed_fields)))

    spreadsheet_mess = {
        "merged_header_season": seasons[0],
        "notes_column": True,  # present every season
        "totals_row_season": seasons[min(3, len(seasons) - 1)],
        "blank_rows_season": seasons[min(5, len(seasons) - 1)],
    }

    bad_zone = None
    if BADZONE_FIELD_ID in farm.identity.canonical_fields:
        bad_zone_season = seasons[min(config.badzone_season_index, len(seasons) - 1)]
        if BADZONE_FIELD_ID in farm.fields_active_in(bad_zone_season):
            bad_zone = {
                "field_id": BADZONE_FIELD_ID,
                "season": bad_zone_season,
                "zone_index": config.badzone_zone_index,
            }

    return DefectPlan(
        no_monitor_seasons=no_monitor_seasons,
        calibration_errors=calibration_errors,
        missing_swath=missing_swath,
        unit_inconsistency_by_season=unit_inconsistency_by_season,
        spreadsheet_mess=spreadsheet_mess,
        total_dollars_season=total_dollars_season,
        transposed_digit={"season": transposed_season, "field_id": transposed_field_id},
        bad_zone=bad_zone,
    )


def build_structural_defect_records(farm: FarmModel, plan: DefectPlan) -> list[dict]:
    """Defect-registry entries for things that aren't tied to one file writer:
    naming drift (spread across the cost ledger's spreadsheet aliases) and the
    two no-monitor seasons (an absence, not a file, so no writer produces it).
    """
    records: list[dict] = []

    drift_field = next(
        f for f in farm.identity.canonical_fields.values() if f.role == "naming_drift"
    )
    canonical_name = drift_field.display_name_by_season[drift_field.active_seasons[0]]
    variants_by_season = {
        s: drift_field.spreadsheet_alias_by_season[s] for s in drift_field.active_seasons
    }
    records.append(
        {
            "defect_id": f"DEF-NAMEDRIFT-{drift_field.field_id}",
            "type": "naming_drift",
            "field_id": drift_field.field_id,
            "season": None,
            "canonical_name": canonical_name,
            "variants_by_season": {str(s): v for s, v in variants_by_season.items()},
            "detail": (
                f"'{canonical_name}' appears in the cost ledger's Field column under "
                "different spellings by season: "
                + ", ".join(f"{s}={v!r}" for s, v in sorted(variants_by_season.items()))
            ),
            "expected_detection": (
                "Alias resolution must map every spelling variant to the same "
                "canonical field before any cross-season comparison."
            ),
            "ground_truth_correction": (
                f"All variants refer to the single canonical field {drift_field.field_id} "
                f"(boundaries/yield-monitor/scale-ticket files consistently call it "
                f"'{canonical_name}')."
            ),
        }
    )

    tie_a_id, tie_b_id = ALIAS_TIE_FIELD_IDS
    if tie_a_id in farm.identity.canonical_fields and tie_b_id in farm.identity.canonical_fields:
        tie_field = farm.identity.canonical_fields[tie_a_id]
        wrong_field = farm.identity.canonical_fields[tie_b_id]
        seasons = farm.config.seasons
        tie_season = seasons[min(ALIAS_TIE_SEASON_INDEX, len(seasons) - 1)]
        correct_name = tie_field.display_name_by_season[tie_season]
        wrong_name = wrong_field.display_name_by_season[tie_season]
        records.append(
            {
                "defect_id": f"DEF-ALIASTIE-{tie_season}-{tie_a_id}",
                "type": "ambiguous_alias_tie",
                "field_id": tie_a_id,
                "season": tie_season,
                "raw_name": ALIAS_TIE_MISSPELLING,
                "naive_wrong_field_id": tie_b_id,
                "detail": (
                    f"Cost ledger name {ALIAS_TIE_MISSPELLING!r} in season {tie_season} "
                    f"doesn't exactly match any boundary name, and {correct_name!r} and "
                    f"{wrong_name!r} have identical acreage that season -- acreage alone "
                    "can't disambiguate, and string similarity favors the wrong field "
                    f"({ALIAS_TIE_NAIVE_WRONG_MATCH!r}, verified via "
                    "difflib.get_close_matches)."
                ),
                "expected_detection": (
                    "This must reach alias_resolution.py's ambiguous_match confirmation "
                    "path (2 acreage candidates) rather than being auto-approved; an "
                    "unconfirmed or auto-approved resolution silently attributes "
                    f"{correct_name!r}'s cost row to {wrong_name!r} instead, dropping "
                    f"{correct_name!r}'s profit record for {tie_season} entirely."
                ),
                "ground_truth_correction": (
                    f"{ALIAS_TIE_MISSPELLING!r} refers to {tie_a_id} ({correct_name!r}), "
                    f"not {tie_b_id} ({wrong_name!r})."
                ),
            }
        )

    ws = farm.weathershortfall
    ws_field = farm.identity.canonical_fields[ws["field_id"]]
    ws_name = ws_field.display_name_by_season[ws["season"]]
    records.append(
        {
            "defect_id": f"DEF-WEATHERSHORTFALL-{ws['season']}-{ws['field_id']}",
            "type": "weather_shortfall",
            "field_id": ws["field_id"],
            "season": ws["season"],
            "true_cause": "weather",
            "detail": (
                f"{ws['season']}'s precipitation was deliberately forced to "
                f"{farm.config.weathershortfall_drought_factor:.0%} of its otherwise-generated "
                f"total -- a genuine drought shared by every field active that season "
                f"(including {ws_name!r}), not a management failure."
            ),
            "expected_detection": (
                "core/expectation.py's attribution must show a large weather-driven "
                f"season_effect and a near-zero residual for {ws_name!r} in "
                f"{ws['season']} -- weather alone should explain the shortfall."
            ),
            "ground_truth_correction": (
                f"{ws['season']} was a bad YEAR for {ws_name!r}, not a bad field: "
                "normal management, forced drought weather."
            ),
        }
    )

    ms = farm.mgmtshortfall
    ms_field = farm.identity.canonical_fields[ms["field_id"]]
    ms_name = ms_field.display_name_by_season[ms["season"]]
    records.append(
        {
            "defect_id": f"DEF-MGMTSHORTFALL-{ms['season']}-{ms['field_id']}",
            "type": "management_shortfall",
            "field_id": ms["field_id"],
            "season": ms["season"],
            "true_cause": "management",
            "detail": (
                f"{ms_name!r}'s {ms['season']} yield was deliberately knocked to "
                f"{farm.config.mgmtshortfall_multiplier:.0%} of what that season's weather "
                "and soil alone would have produced -- a direct management-shortfall "
                "override under otherwise ordinary weather, not a weather effect."
            ),
            "expected_detection": (
                "core/expectation.py's attribution must show ordinary weather for "
                f"{ms['season']} but a large unexplained residual for {ms_name!r} -- "
                "weather does NOT explain this shortfall."
            ),
            "ground_truth_correction": (
                f"{ms['season']} was a bad FIELD (management) year for {ms_name!r}, "
                "not a bad weather year."
            ),
        }
    )

    for season in plan.no_monitor_seasons:
        records.append(
            {
                "defect_id": f"DEF-NOMONITOR-{season}",
                "type": "no_yield_monitor",
                "field_id": None,
                "season": season,
                "detail": (
                    f"No yield monitor files exist for {season} (older combine, no "
                    "monitor); scale tickets are the only yield source that season."
                ),
                "expected_detection": (
                    "Absence of monitor files for this season is expected, not a "
                    "missing-data error."
                ),
                "ground_truth_correction": "Use scale tickets as the sole yield source.",
            }
        )

    return records
