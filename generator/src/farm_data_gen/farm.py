"""Top-level orchestrator: builds the full farm domain model (identity + clean
economics) that every file-writing module and the defect injector consume.
"""

from __future__ import annotations

import dataclasses

from . import weather as weather_mod
from .config import SimConfig
from .economics import (
    FieldSeasonEconomics,
    assign_acres,
    assign_soil_awc,
    compute_farm_economics,
    select_mgmtshortfall,
)
from .field_identity import FarmIdentity, build_field_identity


@dataclasses.dataclass
class FarmModel:
    config: SimConfig
    identity: FarmIdentity
    acres_by_field: dict[str, float]
    soil_awc_by_field: dict[str, float]
    weather_by_season: dict[int, weather_mod.SeasonWeather]
    records: dict[tuple[str, int], FieldSeasonEconomics]
    weathershortfall: dict
    mgmtshortfall: dict

    def seasons(self) -> list[int]:
        return self.config.seasons

    def fields_active_in(self, season: int) -> list[str]:
        return self.identity.active_field_ids(season)

    def record(self, field_id: str, season: int) -> FieldSeasonEconomics:
        return self.records[(field_id, season)]

    def display_name(self, field_id: str, season: int) -> str:
        return self.identity.canonical_fields[field_id].display_name_by_season[season]

    def spreadsheet_alias(self, field_id: str, season: int) -> str:
        return self.identity.canonical_fields[field_id].spreadsheet_alias_by_season[season]

    def season_weather(self, season: int) -> weather_mod.SeasonWeather:
        return self.weather_by_season[season]


def build_farm(config: SimConfig) -> FarmModel:
    identity = build_field_identity(config)
    acres_by_field = assign_acres(identity, config)
    soil_awc_by_field = assign_soil_awc(identity, config)
    weather_by_season = weather_mod.build_weather_by_season(config)

    weathershortfall = weather_mod.select_drought_season(identity, config)
    weather_by_season[weathershortfall["season"]] = weather_mod.force_drought(
        weather_by_season[weathershortfall["season"]],
        factor=config.weathershortfall_drought_factor,
    )

    mgmtshortfall = select_mgmtshortfall(identity, config)
    management_multiplier_overrides = {
        (mgmtshortfall["field_id"], mgmtshortfall["season"]): config.mgmtshortfall_multiplier
    }

    records = compute_farm_economics(
        identity,
        config,
        acres_by_field,
        weather_by_season,
        soil_awc_by_field,
        management_multiplier_overrides=management_multiplier_overrides,
    )
    return FarmModel(
        config=config,
        identity=identity,
        acres_by_field=acres_by_field,
        soil_awc_by_field=soil_awc_by_field,
        weather_by_season=weather_by_season,
        records=records,
        weathershortfall=weathershortfall,
        mgmtshortfall=mgmtshortfall,
    )
