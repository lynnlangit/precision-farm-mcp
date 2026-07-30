"""MCP server: synthetic weather and static soil AWC. Same shape as
mcp-as-applied -- no ConfirmationGate, since weather/soil aren't ambiguous,
nothing for a human to confirm. Offline: reads data/synthetic/weather/*.csv
via farm_core's pipeline/DuckDB ingestion, same as every other server; no
exception to test_no_network.py.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from farm_core import expectation, pipeline
from farm_core.audit import AuditLog

mcp = FastMCP("weather-history")


# Tool functions build one of these, then return its .model_dump() -- see
# mcp_report_export.server for why (a bare Pydantic return type makes
# FastMCP's client-side schema validation reject the refusal shape; a Union
# return type wraps every response in a {"result": ...} envelope). Real
# enforcement happens at construction time, not via the advertised MCP schema.
class SnapshotProvenance(BaseModel):
    data_dir: str
    built_at: str
    source_file_count: int


class GetSeasonWeatherResult(BaseModel):
    season: int
    total_precip_mm: float
    heat_stress_days: int
    heat_stress_threshold_c: float
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class GetFieldSoilResult(BaseModel):
    field_name: str
    awc_in: float
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None

_REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = Path(os.getenv("FARM_DATA_DIR", str(_REPO_ROOT / "data" / "synthetic")))
AUDIT_LOG_PATH = Path(os.getenv("FARM_AUDIT_LOG", str(_REPO_ROOT / "data" / "audit.jsonl")))
CONFIRM_STORE_PATH = Path(
    os.getenv("FARM_CONFIRM_STORE", str(_REPO_ROOT / "data" / "confirmed_mappings.json"))
)


@functools.lru_cache(maxsize=1)
def _snapshot():
    return pipeline.load_query_time_snapshot(DATA_DIR, CONFIRM_STORE_PATH, _audit_log())


@functools.lru_cache(maxsize=1)
def _audit_log() -> AuditLog:
    return AuditLog(AUDIT_LOG_PATH)


def _confirmation_required(exc: pipeline.SnapshotUnconfirmed) -> dict[str, Any]:
    return {
        "error": str(exc),
        "code": "confirmation_required",
        "pending_key": exc.request.key,
        "run": "farm-ingest",
    }


def _confirmation_guarded(fn):
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            return fn(*args, **kwargs)
        except pipeline.SnapshotUnconfirmed as e:
            return _confirmation_required(e)

    return wrapper


def _provenance() -> dict[str, Any]:
    snap = _snapshot()
    return {
        "data_dir": str(snap.data_dir),
        "built_at": snap.built_at,
        "source_file_count": len(snap.source_files),
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_season_weather(season: int) -> dict:
    """Season-wide daily weather aggregate: total precipitation and count of
    days above the heat-stress threshold. Weather is shared across every
    field active that season, not per-field.

    Args:
        season: The season year.

    Returns:
        {"total_precip_mm": ..., "heat_stress_days": ..., "provenance": {...}}
        on success, or {"error": "...", "code": "invalid_input"} for an
        unrecognized season, or {"code": "not_found"} if that season has no
        weather coverage.
    """
    snap = _snapshot()
    if season not in snap.seasons:
        return {
            "error": f"unknown season {season}; known seasons are {snap.seasons}",
            "code": "invalid_input",
        }

    row = snap.con.execute(
        "SELECT SUM(precip_mm), SUM(CASE WHEN temp_max_c > ? THEN 1 ELSE 0 END) "
        "FROM weather_daily WHERE season = ?",
        [expectation.HEAT_STRESS_THRESHOLD_C, season],
    ).fetchone()
    if row is None or row[0] is None:
        return {
            "error": f"no weather coverage for season {season}",
            "code": "not_found",
        }

    _audit_log().log("tool_call", tool="get_season_weather", season=season)
    return GetSeasonWeatherResult(
        season=season,
        total_precip_mm=round(float(row[0]), 1),
        heat_stress_days=int(row[1]),
        heat_stress_threshold_c=expectation.HEAT_STRESS_THRESHOLD_C,
        provenance=SnapshotProvenance(**_provenance()),
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_field_soil(field_name: str) -> dict:
    """Static soil available-water-capacity (AWC), inches, for one field.
    AWC doesn't change season to season, so unlike every other tool in this
    system there's no season argument here.

    Args:
        field_name: The field name, current or from any past season -- drift
            is resolved the same way report-export resolves field names.

    Returns:
        {"field_name": "...", "awc_in": ..., "provenance": {...}} on
        success, or {"error": "...", "code": "not_found"} if the name
        doesn't resolve to a known field with recorded soil data.
    """
    snap = _snapshot()

    row = snap.con.execute(
        "SELECT field_name, awc_in FROM soil_awc WHERE field_name = ?", [field_name]
    ).fetchone()
    if row is None:
        canonical_id = snap.canonical_id_for_name(field_name)
        if canonical_id is not None:
            lineage = snap.identity.lineages[canonical_id]
            current_name = lineage.display_name_by_season[max(lineage.active_seasons)]
            row = snap.con.execute(
                "SELECT field_name, awc_in FROM soil_awc WHERE field_name = ?", [current_name]
            ).fetchone()

    if row is None:
        return {
            "error": f"{field_name!r} does not resolve to a field with recorded soil data",
            "code": "not_found",
        }

    _audit_log().log("tool_call", tool="get_field_soil", field_name=field_name)
    return GetFieldSoilResult(
        field_name=row[0], awc_in=float(row[1]), provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


if __name__ == "__main__":
    mcp.run()
