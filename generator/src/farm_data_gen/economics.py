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
from . import weather as weather_mod
from .config import SimConfig
from .field_identity import ALIAS_TIE_FIELD_IDS, CORN, SOYBEAN, FarmIdentity

MARGINAL_YIELD_PENALTY = 0.72  # marginal field yields at 72% of the normal draw
MARGINAL_COST_PREMIUM = 1.22  # and costs 22% more (poor drainage, more inputs)
CATASTROPHIC_YIELD_FACTOR = 0.10  # a catastrophic year keeps only 10% of yield
# (was 0.25 pre-Phase-C; weather stress now adds its own profit variance across
# seasons, so the override needs a wider margin to stay unambiguously the
# field's worst season -- verified empirically against seed=42, not assumed)


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
    management_multiplier: float | None = None

    def reasoning(self) -> str:
        rent_note = f"${self.cash_rent_per_ac:.2f}/ac cash rent" if self.cash_rent_per_ac else ""
        cat_note = (
            f" Catastrophic loss: {self.catastrophic_cause}." if self.catastrophic_cause else ""
        )
        mgmt_note = (
            f" Management shortfall applied ({self.management_multiplier:.2f}x)."
            if self.management_multiplier is not None
            else ""
        )
        return (
            f"{self.crop} on {self.acres:.1f} ac: {self.yield_bu_ac:.1f} bu/ac x "
            f"${self.price_per_bu:.2f}/bu = ${self.revenue:,.2f} revenue. Costs: "
            f"${self.input_cost_per_ac:.2f}/ac inputs + {rent_note} on {self.acres:.1f} ac "
            f"= ${self.total_cost:,.2f}. Profit = ${self.profit:,.2f} "
            f"(${self.profit_per_acre:.2f}/ac).{cat_note}{mgmt_note}"
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

    # Deliberate defect (DEF-ALIASTIE): force two unrelated "normal" fields to
    # the same acreage. Acreage is otherwise a reliable near-unique fingerprint
    # for alias resolution (see alias_resolution.py); tying two fields' acreage
    # is what turns one ledger misspelling into a genuine 2-candidate ambiguity
    # that must go through confirmation rather than an acreage-match auto-pick.
    # A plain copy, not a fresh RNG draw, so no other field's draw sequence
    # shifts. Both fields are optional filler roster entries, so this only
    # applies when the roster is large enough to include them.
    if ALIAS_TIE_FIELD_IDS[0] in acres and ALIAS_TIE_FIELD_IDS[1] in acres:
        acres[ALIAS_TIE_FIELD_IDS[1]] = acres[ALIAS_TIE_FIELD_IDS[0]]

    return acres


def assign_soil_awc(identity: FarmIdentity, config: SimConfig) -> dict[str, float]:
    """One static available-water-capacity draw (inches) per independent
    lineage -- same one-draw-per-lineage shape as `assign_acres` above, since
    AWC is a soil property that doesn't change when a field is merely
    renamed, split, or merged. It's what makes one season's shared weather
    (weather.py) affect fields differently: higher AWC buffers a water
    deficit, lower AWC doesn't.
    """
    awc: dict[str, float] = {}
    lo, hi = config.soil_awc_in_range

    for field_id, field in identity.canonical_fields.items():
        if field.role in ("split_child", "merge_child"):
            continue
        r = rng_mod.derive_rng(config.random_seed, field_id, "soil_awc")
        awc[field_id] = round(float(r.uniform(lo, hi)), 2)

    for event in identity.events:
        if event.type == "split":
            (parent_id,) = event.parent_field_ids
            for child_id in event.child_field_ids:
                awc[child_id] = awc[parent_id]
        elif event.type == "merge":
            parent_a_id, parent_b_id = event.parent_field_ids
            (child_id,) = event.child_field_ids
            awc[child_id] = round((awc[parent_a_id] + awc[parent_b_id]) / 2, 2)

    return awc


def select_mgmtshortfall(identity: FarmIdentity, config: SimConfig) -> dict:
    """DEF-MGMTSHORTFALL's field+season pick: a *different* continuous-corn
    field than `weather.select_drought_season` picks, and a different season
    index, so its weather that season is ordinary -- the shortfall here is a
    direct, labeled management-multiplier override (see
    `management_multiplier_overrides` on `compute_farm_economics`), not a
    weather effect. Structural, not RNG-driven, same as the drought pick.
    """
    seasons = config.seasons
    season = seasons[min(config.mgmtshortfall_season_index, len(seasons) - 1)]
    fields = [f for f in identity.canonical_fields.values() if f.role == "continuous_corn"]
    field = fields[1] if len(fields) > 1 else fields[0]
    return {"season": season, "field_id": field.field_id}


def _crop_for(field, season: int, config: SimConfig) -> str:
    if field.is_continuous_corn:
        return CORN
    season_index = config.seasons.index(season)
    parity = (season_index + field.rotation_phase) % 2
    return CORN if parity == 0 else SOYBEAN


def compute_farm_economics(
    identity: FarmIdentity,
    config: SimConfig,
    acres_by_field: dict[str, float],
    weather_by_season: dict[int, weather_mod.SeasonWeather],
    soil_awc_by_field: dict[str, float],
    management_multiplier_overrides: dict[tuple[str, int], float] | None = None,
) -> dict[tuple[str, int], FieldSeasonEconomics]:
    """`weather_by_season`/`soil_awc_by_field` drive a causal water+heat stress
    multiplier on top of each field's baseline (genetic/management-potential)
    yield draw -- shared weather affects every field active that season, but
    each field's own soil AWC buffers (or doesn't) the same water deficit
    differently. `management_multiplier_overrides` is the DEF-MGMTSHORTFALL
    hook: a direct, labeled override for a specific (field_id, season),
    applied after the weather stress multiplier and before any catastrophic
    override, standing in for a real management shortfall independent of
    that season's weather.
    """
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

            if field.role == "marginal":
                yield_bu_ac *= MARGINAL_YIELD_PENALTY
                input_cost_per_ac *= MARGINAL_COST_PREMIUM

            season_weather = weather_by_season[season]
            awc = soil_awc_by_field[field_id]
            water_deficit_mm = max(0.0, config.crop_water_need_mm - season_weather.total_precip_mm)
            heat_days = season_weather.heat_stress_days(config.heat_stress_threshold_c)
            heat_penalty = config.heat_stress_k * heat_days
            stress = water_deficit_mm / (1 + awc / config.awc_reference_in) + heat_penalty
            stress_multiplier = min(
                1.0, max(config.min_yield_multiplier, 1 - config.stress_yield_k * stress)
            )
            yield_bu_ac *= stress_multiplier

            management_multiplier = None
            if management_multiplier_overrides is not None:
                management_multiplier = management_multiplier_overrides.get((field_id, season))
                if management_multiplier is not None:
                    yield_bu_ac *= management_multiplier

            catastrophic_cause = None
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
                management_multiplier=management_multiplier,
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
