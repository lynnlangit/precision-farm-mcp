"""Top-level orchestrator: builds the full farm domain model (identity + clean
economics) that every file-writing module and the defect injector consume.
"""

from __future__ import annotations

import dataclasses

from .config import SimConfig
from .economics import FieldSeasonEconomics, assign_acres, compute_farm_economics
from .field_identity import FarmIdentity, build_field_identity


@dataclasses.dataclass
class FarmModel:
    config: SimConfig
    identity: FarmIdentity
    acres_by_field: dict[str, float]
    records: dict[tuple[str, int], FieldSeasonEconomics]

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


def build_farm(config: SimConfig) -> FarmModel:
    identity = build_field_identity(config)
    acres_by_field = assign_acres(identity, config)
    records = compute_farm_economics(identity, config, acres_by_field)
    return FarmModel(
        config=config, identity=identity, acres_by_field=acres_by_field, records=records
    )
