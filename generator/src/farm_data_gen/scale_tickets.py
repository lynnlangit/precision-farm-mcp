"""Elevator scale tickets: one CSV per season, every active field, every load.
This is the authoritative bushel source -- ground_truth.json's profitability
always reconciles to these totals (never to the yield monitor, which is allowed
to drift). Net (dry-basis) bushels per field sum to the true total from
economics.py, give or take ordinary load-to-load moisture variance.

Also carries the settlement price per bushel -- the only place any raw file
records what the grain actually sold for, since revenue can't be recomputed
from yield alone without it. One price per field/season (not per load), same
simplification economics.py already makes internally.
"""

from __future__ import annotations

import csv
import datetime
import io

from . import rng as rng_mod
from .farm import FarmModel

STANDARD_MOISTURE = {"corn": 15.5, "soybean": 13.0}
LOAD_CAPACITY_BU_RANGE = (850.0, 1050.0)
ELEVATOR_NAME = "Prairie Junction Farmers Co-op"

_HEADER = [
    "season",
    "ticket_number",
    "date",
    "field_name",
    "crop",
    "load_number",
    "moisture_pct",
    "gross_bushels",
    "net_bushels",
    "price_per_bu",
    "elevator",
]


def _harvest_date(rng, season: int, crop: str, load_index: int) -> str:
    if crop == "corn":
        start = datetime.date(season, 10, 1)
        span = 35
    else:
        start = datetime.date(season, 9, 15)
        span = 25
    day_offset = int(rng.integers(0, span)) + load_index // 4
    return (start + datetime.timedelta(days=min(day_offset, span))).isoformat()


def build_scale_tickets_by_season(farm: FarmModel) -> dict[int, str]:
    """Return {season: csv_text}."""
    config = farm.config
    out: dict[int, str] = {}
    ticket_counter = 1000

    for season in config.seasons:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(_HEADER)

        for field_id in farm.fields_active_in(season):
            record = farm.record(field_id, season)
            name = farm.display_name(field_id, season)
            true_total_bu = record.yield_bu_ac * record.acres
            standard = STANDARD_MOISTURE[record.crop]

            cap_r = rng_mod.derive_rng(config.random_seed, field_id, "load_capacity", season)
            capacity = float(cap_r.uniform(*LOAD_CAPACITY_BU_RANGE))
            num_loads = max(2, round(true_total_bu / capacity))

            weight_r = rng_mod.derive_rng(config.random_seed, field_id, "load_weights", season)
            raw_weights = weight_r.uniform(0.8, 1.2, size=num_loads)
            weights = raw_weights / raw_weights.sum()
            net_loads = weights * true_total_bu

            moisture_r = rng_mod.derive_rng(config.random_seed, field_id, "load_moisture", season)
            date_r = rng_mod.derive_rng(config.random_seed, field_id, "load_dates", season)
            moist_lo, moist_hi = (
                config.monitor_moisture_pct_corn_range
                if record.crop == "corn"
                else config.monitor_moisture_pct_soybean_range
            )

            moistures = [float(moisture_r.uniform(moist_lo, moist_hi)) for _ in net_loads]
            # Round every load, then let the last one absorb the rounding
            # remainder -- real settlement sheets reconcile to a load total
            # this same way, and it's what makes "scale tickets are the
            # authoritative bushel source" an exact statement rather than an
            # approximate one.
            net_bu_rounded = [round(v, 1) for v in net_loads]
            remainder = round(true_total_bu, 1) - sum(net_bu_rounded)
            net_bu_rounded[-1] = round(net_bu_rounded[-1] + remainder, 1)

            for load_index, (net_bu, moisture) in enumerate(zip(net_bu_rounded, moistures)):
                gross_bu = net_bu * (100 - standard) / (100 - moisture)
                ticket_counter += 1
                writer.writerow(
                    [
                        season,
                        ticket_counter,
                        _harvest_date(date_r, season, record.crop, load_index),
                        name,
                        record.crop,
                        load_index + 1,
                        round(moisture, 1),
                        round(gross_bu, 1),
                        net_bu,
                        round(record.price_per_bu, 2),
                        ELEVATOR_NAME,
                    ]
                )

        out[season] = buf.getvalue()

    return out
