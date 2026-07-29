"""As-applied input logs, last four seasons only (older seasons predate the
farmer's precision-ag controller). One CSV per season, one row per product
application per field. Nitrogen rate units deliberately vary by season -- some
seasons record elemental N in lb/ac, others record gallons/ac of 32% UAN
product -- forcing a unit conversion before any cross-source reconciliation
against the cost ledger is meaningful.
"""

from __future__ import annotations

import csv
import datetime
import io

from . import rng as rng_mod
from .boundaries import compute_field_rings
from .defects import DefectPlan
from .farm import FarmModel
from .field_identity import CORN
from .input_plan import compute_input_rate_plan

UAN32_LB_N_PER_GAL = 3.5392  # 32% N by weight, ~11.06 lb/gal product density

_HEADER = ["timestamp", "field_name", "product", "rate", "rate_unit", "lat", "lon"]


def _point_in_field(rng, ring: list[tuple[float, float]]) -> tuple[float, float]:
    lons = [p[0] for p in ring[:-1]]
    lats = [p[1] for p in ring[:-1]]
    lon = float(rng.uniform(min(lons), max(lons)))
    lat = float(rng.uniform(min(lats), max(lats)))
    return round(lat, 6), round(lon, 6)


def build_as_applied_files(
    farm: FarmModel, plan: DefectPlan
) -> tuple[dict[int, tuple[str, str]], list[dict]]:
    config = farm.config
    rings = compute_field_rings(farm)
    seasons = [s for s in config.seasons if s in plan.unit_inconsistency_by_season]

    files: dict[int, tuple[str, str]] = {}
    defect_records: list[dict] = []

    for season in seasons:
        n_unit_mode = plan.unit_inconsistency_by_season[season]
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(_HEADER)

        for field_id in farm.fields_active_in(season):
            record = farm.record(field_id, season)
            name = farm.display_name(field_id, season)
            r = rng_mod.derive_rng(config.random_seed, field_id, "as_applied", season)
            ring = rings[field_id]
            is_corn = record.crop == CORN
            rate_plan = compute_input_rate_plan(config, field_id, season, record.crop)

            plant_date = datetime.date(season, 5, int(r.integers(1, 20)))
            seed_rate = rate_plan.seed_rate_kseeds_ac
            seed_unit = "kseeds/ac"
            seed_product = "Seed - Corn Hybrid" if is_corn else "Seed - Soybean Variety"
            lat, lon = _point_in_field(r, ring)
            writer.writerow(
                [
                    datetime.datetime.combine(plant_date, datetime.time(7, 30)).isoformat(),
                    name,
                    seed_product,
                    round(seed_rate, 1),
                    seed_unit,
                    lat,
                    lon,
                ]
            )

            n_rate_lb_ac = rate_plan.n_rate_lb_ac
            n_date = datetime.date(season, 4, int(r.integers(10, 28)))
            n_lat, n_lon = _point_in_field(r, ring)
            if n_unit_mode == "lb_per_ac":
                writer.writerow(
                    [
                        datetime.datetime.combine(n_date, datetime.time(9, 0)).isoformat(),
                        name,
                        "Anhydrous Ammonia (82-0-0)",
                        round(n_rate_lb_ac, 1),
                        "lb_N/ac",
                        n_lat,
                        n_lon,
                    ]
                )
            else:
                gal_ac = n_rate_lb_ac / UAN32_LB_N_PER_GAL
                writer.writerow(
                    [
                        datetime.datetime.combine(n_date, datetime.time(9, 0)).isoformat(),
                        name,
                        "UAN 32% (32-0-0)",
                        round(gal_ac, 2),
                        "gal/ac",
                        n_lat,
                        n_lon,
                    ]
                )

            p_rate = rate_plan.p_rate_lb_ac
            k_rate = rate_plan.k_rate_lb_ac
            pk_date = datetime.date(season, 4, int(r.integers(1, 15)))
            p_lat, p_lon = _point_in_field(r, ring)
            writer.writerow(
                [
                    datetime.datetime.combine(pk_date, datetime.time(8, 0)).isoformat(),
                    name,
                    "MAP (11-52-0)",
                    round(p_rate, 1),
                    "lb_P2O5/ac",
                    p_lat,
                    p_lon,
                ]
            )
            writer.writerow(
                [
                    datetime.datetime.combine(pk_date, datetime.time(8, 30)).isoformat(),
                    name,
                    "Potash (0-0-60)",
                    round(k_rate, 1),
                    "lb_K2O/ac",
                    p_lat,
                    p_lon,
                ]
            )

            chem_rate = float(r.uniform(1.5, 3.5))
            chem_date = datetime.date(season, 6, int(r.integers(1, 25)))
            c_lat, c_lon = _point_in_field(r, ring)
            writer.writerow(
                [
                    datetime.datetime.combine(chem_date, datetime.time(14, 0)).isoformat(),
                    name,
                    "Glyphosate + Residual Herbicide",
                    round(chem_rate, 2),
                    "qt/ac",
                    c_lat,
                    c_lon,
                ]
            )

        files[season] = (f"as_applied_{season}.csv", buf.getvalue())

        defect_records.append(
            {
                "defect_id": f"DEF-UNIT-{season}",
                "type": "unit_inconsistency",
                "field_id": None,
                "season": season,
                "detail": (
                    f"As-applied nitrogen recorded in lb_N/ac for {season}."
                    if n_unit_mode == "lb_per_ac"
                    else (
                        f"As-applied nitrogen recorded in gal/ac of 32% UAN product for "
                        f"{season}; convert using {UAN32_LB_N_PER_GAL} lb N per gallon."
                    )
                ),
                "expected_detection": (
                    "Any cross-season N-rate comparison or as-applied-vs-ledger cost "
                    "reconciliation must normalize units before comparing."
                ),
                "ground_truth_correction": (
                    "Elemental N lb/ac is the canonical unit; convert gal/ac readings "
                    f"by multiplying by {UAN32_LB_N_PER_GAL} lb N/gal."
                ),
            }
        )

    return files, defect_records
