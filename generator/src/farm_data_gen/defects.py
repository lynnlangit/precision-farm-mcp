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
from .field_identity import scaled_indices


@dataclasses.dataclass
class DefectPlan:
    no_monitor_seasons: list[int]
    calibration_errors: list[dict]  # {field_id, season, error_pct} (signed)
    missing_swath: dict  # {field_id, season, gap_fraction}
    unit_inconsistency_by_season: dict[int, str]  # season -> "lb_per_ac" | "product_per_ac"
    spreadsheet_mess: dict  # keyed defect assignments, see below
    total_dollars_season: int
    transposed_digit: dict  # {season, field_id, original, transposed}


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

    return DefectPlan(
        no_monitor_seasons=no_monitor_seasons,
        calibration_errors=calibration_errors,
        missing_swath=missing_swath,
        unit_inconsistency_by_season=unit_inconsistency_by_season,
        spreadsheet_mess=spreadsheet_mess,
        total_dollars_season=total_dollars_season,
        transposed_digit={"season": transposed_season, "field_id": transposed_field_id},
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
