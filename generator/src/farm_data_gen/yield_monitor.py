"""Per-field, per-season yield monitor point CSVs. Not generated for the two
oldest seasons (older combine, scale tickets only) or, deliberately, made to
disagree with scale tickets by 3-7% for a handful of (field, season) pairs
(the calibration-error defect), and given a spatial coverage gap for one
(field, season) pair (the missing-swath / GPS-dropout defect) while its total
still reconciles fine -- the point of that defect is that a naive "is there a
gap" check would wrongly flag a real harvest as incomplete.
"""

from __future__ import annotations

import csv
import datetime
import io

from . import rng as rng_mod
from .boundaries import compute_field_rings
from .defects import DefectPlan
from .farm import FarmModel
from .scale_tickets import STANDARD_MOISTURE

_HEADER = ["timestamp", "lat", "lon", "wet_bu_ac", "dry_bu_ac", "moisture_pct"]

_NATURAL_NOISE_RANGE = (0.995, 1.005)


def _bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lons = [p[0] for p in ring[:-1]]
    lats = [p[1] for p in ring[:-1]]
    return min(lons), max(lons), min(lats), max(lats)


def build_yield_monitor_files(
    farm: FarmModel, plan: DefectPlan
) -> tuple[dict[tuple[str, int], tuple[str, str]], list[dict]]:
    """Return ({(field_id, season): (filename, csv_text)}, defect_records)."""
    config = farm.config
    rings = compute_field_rings(farm)

    calibration_by_key = {
        (e["field_id"], e["season"]): e["error_pct"] for e in plan.calibration_errors
    }
    swath_key = (plan.missing_swath["field_id"], plan.missing_swath["season"])

    files: dict[tuple[str, int], tuple[str, str]] = {}
    defect_records: list[dict] = []

    for season in config.seasons:
        if season in plan.no_monitor_seasons:
            continue
        for field_id in farm.fields_active_in(season):
            record = farm.record(field_id, season)
            name = farm.display_name(field_id, season)
            true_total_bu = record.yield_bu_ac * record.acres
            standard = STANDARD_MOISTURE[record.crop]

            key = (field_id, season)
            error_pct = calibration_by_key.get(key)
            if error_pct is not None:
                monitor_total_bu = true_total_bu * (1 + error_pct)
            else:
                noise_r = rng_mod.derive_rng(config.random_seed, field_id, "monitor_noise", season)
                monitor_total_bu = true_total_bu * float(noise_r.uniform(*_NATURAL_NOISE_RANGE))

            density_r = rng_mod.derive_rng(config.random_seed, field_id, "point_density", season)
            density = float(density_r.uniform(*config.yield_point_density_per_acre_range))
            target_point_count = max(20, round(density * record.acres))

            min_lon, max_lon, min_lat, max_lat = _bbox(rings[field_id])
            pos_r = rng_mod.derive_rng(config.random_seed, field_id, "point_positions", season)

            gap_bounds = None
            if key == swath_key:
                gap_fraction = plan.missing_swath["gap_fraction"]
                gap_start_lon = max_lon - (max_lon - min_lon) * gap_fraction
                gap_bounds = (gap_start_lon, max_lon)

            lons: list[float] = []
            lats: list[float] = []
            attempts = 0
            while len(lons) < target_point_count and attempts < target_point_count * 20:
                attempts += 1
                lon = float(pos_r.uniform(min_lon, max_lon))
                lat = float(pos_r.uniform(min_lat, max_lat))
                if gap_bounds and gap_bounds[0] <= lon <= gap_bounds[1]:
                    continue
                lons.append(lon)
                lats.append(lat)

            point_count = len(lons)
            weight_r = rng_mod.derive_rng(config.random_seed, field_id, "point_weights", season)
            raw_weights = weight_r.uniform(0.7, 1.3, size=point_count)
            weights = raw_weights / raw_weights.sum()
            dry_bushels = weights * monitor_total_bu
            area_per_point_ac = record.acres / point_count

            moisture_r = rng_mod.derive_rng(config.random_seed, field_id, "point_moisture", season)
            time_r = rng_mod.derive_rng(config.random_seed, field_id, "point_time", season)
            moist_lo, moist_hi = (
                config.monitor_moisture_pct_corn_range
                if record.crop == "corn"
                else config.monitor_moisture_pct_soybean_range
            )
            harvest_day = (
                datetime.date(season, 10, 5)
                if record.crop == "corn"
                else datetime.date(season, 9, 20)
            )

            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            writer.writerow(_HEADER)
            for i in range(point_count):
                moisture = float(moisture_r.uniform(moist_lo, moist_hi))
                dry_bu_ac = dry_bushels[i] / area_per_point_ac
                wet_bu_ac = dry_bu_ac * (100 - standard) / (100 - moisture)
                minute_offset = int(time_r.integers(0, 600))
                ts = datetime.datetime.combine(
                    harvest_day, datetime.time(8, 0)
                ) + datetime.timedelta(minutes=minute_offset)
                writer.writerow(
                    [
                        ts.isoformat(),
                        round(lats[i], 6),
                        round(lons[i], 6),
                        round(wet_bu_ac, 2),
                        round(dry_bu_ac, 2),
                        round(moisture, 1),
                    ]
                )

            slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
            filename = f"yield_monitor_{slug}_{season}.csv"
            files[key] = (filename, buf.getvalue())

            if error_pct is not None:
                defect_records.append(
                    {
                        "defect_id": f"DEF-CAL-{season}-{field_id}",
                        "type": "yield_monitor_calibration_error",
                        "field_id": field_id,
                        "season": season,
                        "monitor_total_bu": round(monitor_total_bu, 1),
                        "scale_ticket_total_bu": round(true_total_bu, 1),
                        "pct_diff": round(error_pct * 100, 1),
                        "detail": (
                            f"Yield monitor total ({monitor_total_bu:,.0f} bu) is "
                            f"{error_pct * 100:+.1f}% off the scale ticket total "
                            f"({true_total_bu:,.0f} bu) on {name}."
                        ),
                        "expected_detection": (
                            "Reconciling yield_monitor totals against scale_tickets "
                            "for this field/season should flag a discrepancy >3%."
                        ),
                        "ground_truth_correction": (
                            "Scale ticket total is authoritative; ground_truth "
                            "profitability uses it, not the monitor total."
                        ),
                    }
                )
            if key == swath_key:
                defect_records.append(
                    {
                        "defect_id": f"DEF-SWATH-{season}-{field_id}",
                        "type": "missing_swath",
                        "field_id": field_id,
                        "season": season,
                        "gap_fraction": round(plan.missing_swath["gap_fraction"], 3),
                        "detail": (
                            f"GPS dropout on {name}: no yield monitor points recorded in "
                            f"the eastern {plan.missing_swath['gap_fraction'] * 100:.0f}% "
                            "of the field, though it was fully harvested."
                        ),
                        "expected_detection": (
                            "A spatial coverage check on the yield monitor points shows a "
                            "gap; scale ticket / monitor totals still reconcile normally, "
                            "so a totals-only check would miss this."
                        ),
                        "ground_truth_correction": (
                            "Not a real unharvested area -- do not treat the gap as zero "
                            "yield; total bushels for the field are unaffected."
                        ),
                    }
                )

    return files, defect_records
