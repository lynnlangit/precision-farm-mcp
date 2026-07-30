"""All tunable ranges live here, as named constants — never as magic numbers
scattered through the generator modules. Override any of them via a --config
JSON file (see cli.py); the CLI's --fields/--seasons flags override num_fields
and num_seasons directly.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class SimConfig:
    num_fields: int = 12
    start_season: int = 2016
    num_seasons: int = 10

    field_acres_range: tuple[float, float] = (60.0, 220.0)

    # Yield, bu/ac
    corn_yield_bu_ac_range: tuple[float, float] = (150.0, 200.0)
    soybean_yield_bu_ac_range: tuple[float, float] = (40.0, 55.0)

    # Cash price, $/bu (plausible ND 2016-2025 range)
    corn_price_bu_range: tuple[float, float] = (3.20, 5.80)
    soybean_price_bu_range: tuple[float, float] = (8.00, 14.00)

    # Input cost, $/ac (all-in seed+chem+fert+fuel+misc, excludes rent)
    corn_cost_ac_range: tuple[float, float] = (350.0, 450.0)
    soybean_cost_ac_range: tuple[float, float] = (220.0, 320.0)

    # Cash rent, $/ac/season
    cash_rent_ac_range: tuple[float, float] = (150.0, 250.0)

    # Unit prices, by season (feed cost_ledger unit-price tab)
    n_price_per_lb_range: tuple[float, float] = (0.35, 0.65)
    p_price_per_lb_range: tuple[float, float] = (0.40, 0.70)
    k_price_per_lb_range: tuple[float, float] = (0.30, 0.55)
    seed_price_corn_per_unit_range: tuple[float, float] = (110.0, 150.0)  # $/80k-seed unit
    seed_price_soy_per_unit_range: tuple[float, float] = (28.0, 40.0)  # $/140k-seed unit
    chemical_price_per_ac_range: tuple[float, float] = (35.0, 60.0)
    fuel_price_per_gal_range: tuple[float, float] = (2.20, 4.20)

    # As-applied rates
    n_rate_lb_ac_corn_range: tuple[float, float] = (140.0, 180.0)
    n_rate_lb_ac_soybean_range: tuple[float, float] = (0.0, 20.0)

    # Yield monitor
    yield_point_density_per_acre_range: tuple[float, float] = (2.0, 4.0)
    monitor_moisture_pct_corn_range: tuple[float, float] = (14.0, 24.0)
    monitor_moisture_pct_soybean_range: tuple[float, float] = (10.0, 16.0)

    # Defect knobs
    calibration_error_seasons_count: int = 4
    calibration_error_pct_range: tuple[float, float] = (0.03, 0.07)
    no_monitor_seasons_count: int = 2  # oldest N seasons: scale tickets only
    as_applied_seasons_count: int = 4  # newest N seasons only
    split_season_index: int = 4  # season 5 (0-indexed: index 4)
    merge_season_index: int = 6  # season 7
    rename_season_index: int = 5  # season 6
    rental_lost_last_season_index: int = 3  # present seasons 1-4 (indices 0-3)
    missing_swath_season_index: int = 8  # a GPS-dropout season

    # Weather / soil / causal-yield stress (Phase C)
    soil_awc_in_range: tuple[float, float] = (4.0, 9.0)  # available water capacity, inches
    crop_water_need_mm: float = 450.0  # season-long precip need, both crops (simplification)
    awc_reference_in: float = 6.5  # AWC at which soil buffering halves the water deficit
    heat_stress_threshold_c: float = 32.0
    heat_stress_k: float = 0.015  # stress added per day above the heat threshold
    stress_yield_k: float = 0.004  # yield-multiplier loss per unit of combined stress
    min_yield_multiplier: float = 0.5  # stress can never take yield below this fraction
    # (stress_yield_k/min_yield_multiplier tuned so ordinary season-to-season
    # weather variance stays a real but modest effect -- gentle enough that it
    # doesn't spuriously trigger the MAD-outlier rule on its own; verified
    # empirically against seed=42, not assumed. DEF-WEATHERSHORTFALL's forced
    # drought is what should read as a genuinely severe, attributable event.)
    weathershortfall_drought_factor: float = 0.35  # DEF-WEATHERSHORTFALL precip scale-down
    mgmtshortfall_multiplier: float = 0.65  # DEF-MGMTSHORTFALL override, applied post-weather
    weathershortfall_season_index: int = 2  # season for the forced drought
    mgmtshortfall_season_index: int = 7  # a different season, normal weather, forced management

    # Boundary CRS mix: season indices (0-based) whose GeoJSON is EPSG:26914
    # (NAD83 / UTM zone 14N) instead of the default EPSG:4326.
    utm_crs_season_indices: tuple[int, ...] = (1, 3, 4, 7)

    # Farm location (approximate eastern North Dakota corn/soybean country)
    base_lat: float = 47.35
    base_lon: float = -97.85
    utm_central_meridian: float = -99.0  # EPSG:26914 zone 14N

    random_seed: int = 42

    def with_overrides(self, **overrides: object) -> "SimConfig":
        return dataclasses.replace(self, **overrides)

    @property
    def seasons(self) -> list[int]:
        return list(range(self.start_season, self.start_season + self.num_seasons))
