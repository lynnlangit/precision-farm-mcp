"""Shared input-rate and unit-price plan, used by both as_applied.py (to
render the actual application log) and cost_ledger.py (to derive seed and
fertilizer $/ac for the seasons where as-applied data exists too).

Without this, the ledger's seed/fertilizer costs and the as-applied rate x
unit price estimate would be drawn from entirely independent RNG streams --
two "independent paths to the same figure" that would never actually agree,
even with zero defects. That would drown out the one deliberately injected
outlier (the transposed digit) in a sea of meaningless noise. Tying them to
one shared rate plan (plus a small bookkeeping-noise factor) makes the
non-defect case genuinely reconcile, the way the yield-monitor/scale-ticket
pair already does.
"""

from __future__ import annotations

import dataclasses

from . import rng as rng_mod
from .config import SimConfig
from .field_identity import CORN

SEED_RATE_CORN_KSEEDS_AC_RANGE = (32.0, 36.0)
SEED_RATE_SOYBEAN_KSEEDS_AC_RANGE = (140.0, 160.0)
P_RATE_LB_AC_RANGE = (30.0, 70.0)
K_RATE_LB_AC_RANGE = (20.0, 60.0)

SEEDS_PER_UNIT_CORN = 80_000
SEEDS_PER_UNIT_SOYBEAN = 140_000

BOOKKEEPING_NOISE_RANGE = (0.95, 1.05)


@dataclasses.dataclass(frozen=True)
class InputRatePlan:
    seed_rate_kseeds_ac: float
    n_rate_lb_ac: float
    p_rate_lb_ac: float
    k_rate_lb_ac: float


@dataclasses.dataclass(frozen=True)
class UnitPrices:
    seed_corn_price_per_unit: float
    seed_soybean_price_per_unit: float
    n_price_per_lb: float
    p_price_per_lb: float
    k_price_per_lb: float
    chemical_price_per_ac: float
    fuel_price_per_gal: float


def compute_input_rate_plan(
    config: SimConfig, field_id: str, season: int, crop: str
) -> InputRatePlan:
    r = rng_mod.derive_rng(config.random_seed, field_id, "input_rate_plan", season)
    is_corn = crop == CORN
    seed_lo, seed_hi = (
        SEED_RATE_CORN_KSEEDS_AC_RANGE if is_corn else SEED_RATE_SOYBEAN_KSEEDS_AC_RANGE
    )
    n_lo, n_hi = config.n_rate_lb_ac_corn_range if is_corn else config.n_rate_lb_ac_soybean_range
    return InputRatePlan(
        seed_rate_kseeds_ac=float(r.uniform(seed_lo, seed_hi)),
        n_rate_lb_ac=float(r.uniform(n_lo, n_hi)),
        p_rate_lb_ac=float(r.uniform(*P_RATE_LB_AC_RANGE)),
        k_rate_lb_ac=float(r.uniform(*K_RATE_LB_AC_RANGE)),
    )


def compute_unit_prices(config: SimConfig, season: int) -> UnitPrices:
    r = rng_mod.derive_rng(config.random_seed, "unit_price", season)
    return UnitPrices(
        seed_corn_price_per_unit=float(r.uniform(*config.seed_price_corn_per_unit_range)),
        seed_soybean_price_per_unit=float(r.uniform(*config.seed_price_soy_per_unit_range)),
        n_price_per_lb=float(r.uniform(*config.n_price_per_lb_range)),
        p_price_per_lb=float(r.uniform(*config.p_price_per_lb_range)),
        k_price_per_lb=float(r.uniform(*config.k_price_per_lb_range)),
        chemical_price_per_ac=float(r.uniform(*config.chemical_price_per_ac_range)),
        fuel_price_per_gal=float(r.uniform(*config.fuel_price_per_gal_range)),
    )


def seed_cost_per_ac(plan: InputRatePlan, prices: UnitPrices, crop: str) -> float:
    if crop == CORN:
        seeds_per_unit, price = SEEDS_PER_UNIT_CORN, prices.seed_corn_price_per_unit
    else:
        seeds_per_unit, price = SEEDS_PER_UNIT_SOYBEAN, prices.seed_soybean_price_per_unit
    return (plan.seed_rate_kseeds_ac * 1000 / seeds_per_unit) * price


def fertilizer_cost_per_ac(plan: InputRatePlan, prices: UnitPrices) -> float:
    return (
        plan.n_rate_lb_ac * prices.n_price_per_lb
        + plan.p_rate_lb_ac * prices.p_price_per_lb
        + plan.k_rate_lb_ac * prices.k_price_per_lb
    )
