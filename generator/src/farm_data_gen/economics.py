"""The "answer key" arithmetic: true (pre-defect) yield, price, cost and profit
for every active (field, season) pair. This is what ground_truth.json's
profitability figures are derived from. Everything downstream that writes
messy/defective files (yield monitor, scale tickets, cost ledger) starts from
these true numbers and then perturbs its own copy -- the truth here never
carries the injected errors itself.
"""

from __future__ import annotations

import dataclasses

from . import rng as rng_mod
from .config import SimConfig
from .field_identity import CORN, SOYBEAN, FarmIdentity

MARGINAL_YIELD_PENALTY = 0.72  # marginal field yields at 72% of the normal draw
MARGINAL_COST_PREMIUM = 1.22  # and costs 22% more (poor drainage, more inputs)
CATASTROPHIC_YIELD_FACTOR = 0.25  # a catastrophic year keeps only 25% of yield


@dataclasses.dataclass
class FieldSeasonEconomics:
    field_id: str
    season: int
    crop: str
    acres: float
    yield_bu_ac: float
    price_per_bu: float
    revenue: float
    input_cost_per_ac: float
    cash_rent_per_ac: float
    total_cost: float
    profit: float
    profit_per_acre: float
    catastrophic_cause: str | None = None

    def reasoning(self) -> str:
        rent_note = f"${self.cash_rent_per_ac:.2f}/ac cash rent" if self.cash_rent_per_ac else ""
        cat_note = (
            f" Catastrophic loss: {self.catastrophic_cause}." if self.catastrophic_cause else ""
        )
        return (
            f"{self.crop} on {self.acres:.1f} ac: {self.yield_bu_ac:.1f} bu/ac x "
            f"${self.price_per_bu:.2f}/bu = ${self.revenue:,.2f} revenue. Costs: "
            f"${self.input_cost_per_ac:.2f}/ac inputs + {rent_note} on {self.acres:.1f} ac "
            f"= ${self.total_cost:,.2f}. Profit = ${self.profit:,.2f} "
            f"(${self.profit_per_acre:.2f}/ac).{cat_note}"
        )


def assign_acres(identity: FarmIdentity, config: SimConfig) -> dict[str, float]:
    """One acreage draw per independent lineage; split/merge conserve acres
    exactly so ground_truth's self-consistency check always passes.
    """
    acres: dict[str, float] = {}
    lo, hi = config.field_acres_range
    handled: set[str] = set()

    for field_id, field in identity.canonical_fields.items():
        if field.role == "split_child":
            continue  # handled via parent below
        if field.role == "merge_child":
            continue  # handled via parents below
        r = rng_mod.derive_rng(config.random_seed, field_id, "acres")
        acres[field_id] = round(float(r.uniform(lo, hi)), 1)
        handled.add(field_id)

    for event in identity.events:
        if event.type == "split":
            (parent_id,) = event.parent_field_ids
            child_a_id, child_b_id = event.child_field_ids
            parent_acres = acres[parent_id]
            r = rng_mod.derive_rng(config.random_seed, parent_id, "split_fraction")
            fraction = float(r.uniform(0.35, 0.65))
            a_acres = round(parent_acres * fraction, 1)
            b_acres = round(parent_acres - a_acres, 1)
            acres[child_a_id] = a_acres
            acres[child_b_id] = b_acres
        elif event.type == "merge":
            parent_a_id, parent_b_id = event.parent_field_ids
            (child_id,) = event.child_field_ids
            acres[child_id] = round(acres[parent_a_id] + acres[parent_b_id], 1)

    return acres


def _crop_for(field, season: int, config: SimConfig) -> str:
    if field.is_continuous_corn:
        return CORN
    season_index = config.seasons.index(season)
    parity = (season_index + field.rotation_phase) % 2
    return CORN if parity == 0 else SOYBEAN


def compute_farm_economics(
    identity: FarmIdentity, config: SimConfig, acres_by_field: dict[str, float]
) -> dict[tuple[str, int], FieldSeasonEconomics]:
    records: dict[tuple[str, int], FieldSeasonEconomics] = {}

    catastrophic_field = next(
        (f for f in identity.canonical_fields.values() if f.role == "catastrophic"), None
    )
    catastrophic_season = None
    if catastrophic_field is not None:
        eligible = catastrophic_field.active_seasons
        idx = min(4, len(eligible) - 1)
        catastrophic_season = eligible[idx]

    for field_id, field in identity.canonical_fields.items():
        acres = acres_by_field[field_id]
        for season in field.active_seasons:
            crop = _crop_for(field, season, config)
            is_corn = crop == CORN

            yield_r = rng_mod.derive_rng(config.random_seed, field_id, "yield", season)
            yield_lo, yield_hi = (
                config.corn_yield_bu_ac_range if is_corn else config.soybean_yield_bu_ac_range
            )
            yield_bu_ac = float(yield_r.uniform(yield_lo, yield_hi))

            price_r = rng_mod.derive_rng(config.random_seed, "price", crop, season)
            price_lo, price_hi = (
                config.corn_price_bu_range if is_corn else config.soybean_price_bu_range
            )
            price_per_bu = float(price_r.uniform(price_lo, price_hi))

            cost_r = rng_mod.derive_rng(config.random_seed, field_id, "input_cost", season)
            cost_lo, cost_hi = (
                config.corn_cost_ac_range if is_corn else config.soybean_cost_ac_range
            )
            input_cost_per_ac = float(cost_r.uniform(cost_lo, cost_hi))

            rent_r = rng_mod.derive_rng(config.random_seed, field_id, "cash_rent")
            rent_lo, rent_hi = config.cash_rent_ac_range
            cash_rent_per_ac = float(rent_r.uniform(rent_lo, rent_hi))

            catastrophic_cause = None
            if field.role == "marginal":
                yield_bu_ac *= MARGINAL_YIELD_PENALTY
                input_cost_per_ac *= MARGINAL_COST_PREMIUM
            if field.role == "catastrophic" and season == catastrophic_season:
                yield_bu_ac *= CATASTROPHIC_YIELD_FACTOR
                catastrophic_cause = "hail"

            revenue = yield_bu_ac * acres * price_per_bu
            total_cost = (input_cost_per_ac + cash_rent_per_ac) * acres
            profit = revenue - total_cost

            records[(field_id, season)] = FieldSeasonEconomics(
                field_id=field_id,
                season=season,
                crop=crop,
                acres=acres,
                yield_bu_ac=round(yield_bu_ac, 2),
                price_per_bu=round(price_per_bu, 2),
                revenue=round(revenue, 2),
                input_cost_per_ac=round(input_cost_per_ac, 2),
                cash_rent_per_ac=round(cash_rent_per_ac, 2),
                total_cost=round(total_cost, 2),
                profit=round(profit, 2),
                profit_per_acre=round(profit / acres, 2) if acres else 0.0,
                catastrophic_cause=catastrophic_cause,
            )

    return records


def find_marginal_field_id(identity: FarmIdentity) -> str:
    return next(f.field_id for f in identity.canonical_fields.values() if f.role == "marginal")


def find_catastrophic_info(
    identity: FarmIdentity, records: dict[tuple[str, int], FieldSeasonEconomics]
) -> dict:
    field = next(f for f in identity.canonical_fields.values() if f.role == "catastrophic")
    season = next(
        s for (fid, s), rec in records.items() if fid == field.field_id and rec.catastrophic_cause
    )
    return {"field_id": field.field_id, "season": season, "cause": "hail"}
