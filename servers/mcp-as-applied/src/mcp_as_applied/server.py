"""MCP server: as-applied input logs (last four seasons only). Thin
transport wrapper around the as_applied_events table -- absence of data for
older seasons is expected and returned as an empty, non-error result.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from farm_core import field_conditions, pipeline
from farm_core.audit import AuditLog

mcp = FastMCP("as-applied")


# Tool functions build one of these, then return its .model_dump() -- see
# mcp_report_export.server for why (a bare Pydantic return type makes
# FastMCP's client-side schema validation reject the refusal shape; a Union
# return type wraps every response in a {"result": ...} envelope). Real
# enforcement happens at construction time, not via the advertised MCP schema.
class SnapshotProvenance(BaseModel):
    data_dir: str
    built_at: str
    source_file_count: int


class AsAppliedEvent(BaseModel):
    timestamp: str
    product: str
    rate: float
    rate_unit: str
    lat: float
    lon: float


class GetAsAppliedEventsResult(BaseModel):
    events: list[AsAppliedEvent]
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None

class AppliedInput(BaseModel):
    input: str
    product: str
    rate: float
    unit: str
    as_logged_rate: float
    as_logged_unit: str
    converted: bool


class GetAppliedInputsResult(BaseModel):
    field_name: str
    asked_name: str
    season: int
    crop: str | None
    logged: bool
    logged_seasons: list[int]
    applied_inputs: list[AppliedInput]
    nitrogen_lb_n_ac: float | None
    uan32_lb_n_per_gal: float
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class NitrogenSeason(BaseModel):
    season: int
    field_name: str
    crop: str | None
    product: str
    n_lb_n_ac: float
    as_logged_rate: float
    as_logged_unit: str
    converted: bool


class NitrogenCropRange(BaseModel):
    num_seasons: int
    min_lb_n_ac: float
    min_season: int
    max_lb_n_ac: float
    max_season: int
    spread_lb_n_ac: float


class GetNitrogenHistoryResult(BaseModel):
    field_name: str
    asked_name: str
    nitrogen_by_season: list[NitrogenSeason]
    nitrogen_by_crop: dict[str, NitrogenCropRange]
    logs_start_season: int
    uan32_lb_n_per_gal: float
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
def get_as_applied_events(field_name: str, season: int) -> dict:
    """List as-applied input events (seed, N, P, K, chemical) for one
    field/season. As-applied logs only exist for the newest four seasons --
    an older season returns an empty list, not an error.

    Args:
        field_name: The stable boundary field name.
        season: The season year.

    Returns:
        {"events": [...], "provenance": {...}} on success (events may be
        empty), or {"error": "...", "code": "invalid_input"} for an
        unrecognized season.
    """
    snap = _snapshot()
    if season not in snap.seasons:
        return {
            "error": f"unknown season {season}; known seasons are {snap.seasons}",
            "code": "invalid_input",
        }

    rows = snap.con.execute(
        "SELECT timestamp, product, rate, rate_unit, lat, lon FROM as_applied_events "
        "WHERE field_name = ? AND season = ? ORDER BY timestamp",
        [field_name, season],
    ).fetchall()

    _audit_log().log(
        "tool_executed", tool="get_as_applied_events", field_name=field_name, season=season
    )
    events = [
        {
            "timestamp": str(r[0]),
            "product": r[1],
            "rate": r[2],
            "rate_unit": r[3],
            "lat": r[4],
            "lon": r[5],
        }
        for r in rows
    ]
    return GetAsAppliedEventsResult(
        events=events, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_applied_inputs(field_name: str, season: int) -> dict:
    """What the as-applied log shows for one field and season: seed, N, P,
    K and herbicide rates. Nitrogen is always reported in lb N/ac; a season
    logged in gal/ac of UAN 32% is converted (the as-logged reading is kept
    beside it). A season before the logs start returns logged=false and an
    empty list, not an error.

    Args:
        field_name: The field name, current or from a past season.
        season: The season year.

    Returns:
        {"applied_inputs": [...], "nitrogen_lb_n_ac": ..., "logged": ...,
        "provenance": {...}} on success, or {"error": "...", "code": ...}
        for an unknown season or field.
    """
    try:
        summary = field_conditions.applied_inputs(_snapshot(), field_name, season)
    except field_conditions.LookupRefused as e:
        return {"error": e.reason, "code": e.code}
    _audit_log().log(
        "tool_executed", tool="get_applied_inputs", field_name=field_name, season=season
    )
    return GetAppliedInputsResult(
        **summary, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_nitrogen_history(field_name: str) -> dict:
    """Nitrogen in lb N/ac for every logged season of one field, with the
    crop each season and the lowest/highest rate per crop (corn and soybean
    take very different N, so they are never compared with each other).

    Args:
        field_name: The field name, current or from a past season.

    Returns:
        {"nitrogen_by_season": [...], "nitrogen_by_crop": {...},
        "logs_start_season": ..., "provenance": {...}} on success, or
        {"error": "...", "code": "not_found"}.
    """
    try:
        summary = field_conditions.nitrogen_history(_snapshot(), field_name)
    except field_conditions.LookupRefused as e:
        return {"error": e.reason, "code": e.code}
    _audit_log().log("tool_executed", tool="get_nitrogen_history", field_name=field_name)
    return GetNitrogenHistoryResult(
        **summary, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


if __name__ == "__main__":
    mcp.run()
