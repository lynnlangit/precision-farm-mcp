"""MCP server: synthetic weather and static soil AWC. Same shape as
mcp-as-applied -- no ConfirmationGate, since weather/soil aren't ambiguous,
nothing for a human to confirm. Offline: reads data/synthetic/weather/*.csv
via farm_core's pipeline/DuckDB ingestion, same as every other server; no
exception to test_no_network.py.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from farm_core import field_conditions
from farm_core.server_support import (
    SnapshotProvenance,
    audit_log as _audit_log,
    confirmation_guarded as _confirmation_guarded,
    provenance as _provenance,
    snapshot as _snapshot,
)

mcp = FastMCP("weather-history")


# Tool functions build one of these, then return its .model_dump() -- see
# mcp_report_export.server for why (a bare Pydantic return type makes
# FastMCP's client-side schema validation reject the refusal shape; a Union
# return type wraps every response in a {"result": ...} envelope). Real
# enforcement happens at construction time, not via the advertised MCP schema.
class GetSeasonWeatherResult(BaseModel):
    season: int
    total_precip_mm: float
    farm_average_precip_mm: float
    pct_vs_farm_average: int
    num_seasons_compared: int
    precip_rank_driest: int
    crop_water_need_mm: float
    precip_short_of_need_mm: float
    heat_stress_days: int
    farm_average_heat_stress_days: float
    heat_stress_threshold_c: float
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class GetFieldSoilResult(BaseModel):
    field_name: str
    asked_name: str
    awc_in: float
    farm_min_awc_in: float
    min_field_name: str
    farm_max_awc_in: float
    max_field_name: str
    num_current_fields: int
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_season_weather(season: int) -> dict:
    """Season-wide weather: total precipitation and days above the
    heat-stress threshold, set against every season on record (farm
    average, driest-to-wettest rank, and the crop water need). Weather is
    shared across every field active that season, not per-field.

    Args:
        season: The season year.

    Returns:
        {"total_precip_mm": ..., "farm_average_precip_mm": ...,
        "heat_stress_days": ..., "provenance": {...}} on success, or
        {"error": "...", "code": "invalid_input"} for an unrecognized
        season, or {"code": "not_found"} if that season has no weather
        coverage.
    """
    try:
        summary = field_conditions.season_weather_summary(_snapshot(), season)
    except field_conditions.LookupRefused as e:
        return {"error": e.reason, "code": e.code}
    _audit_log().log("tool_executed", tool="get_season_weather", season=season)
    return GetSeasonWeatherResult(
        **summary, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_field_soil(field_name: str) -> dict:
    """Static soil available-water-capacity (AWC), inches, for one field,
    with the lowest and highest AWC among the farm's current fields. AWC
    doesn't change season to season, so there's no season argument here.

    Args:
        field_name: The field name, current or from any past season -- drift
            is resolved the same way report-export resolves field names.

    Returns:
        {"field_name": "...", "awc_in": ..., "farm_min_awc_in": ...,
        "provenance": {...}} on success, or {"error": "...", "code":
        "not_found"} if the name doesn't resolve to a known field with
        recorded soil data.
    """
    try:
        summary = field_conditions.field_soil_summary(_snapshot(), field_name)
    except field_conditions.LookupRefused as e:
        return {"error": e.reason, "code": e.code}
    _audit_log().log("tool_executed", tool="get_field_soil", field_name=field_name)
    return GetFieldSoilResult(
        **summary, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


if __name__ == "__main__":
    mcp.run()
