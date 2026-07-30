"""MCP server: canonical field identity and naming-drift alias resolution.
Thin transport wrapper around farm_core.field_identity /
farm_core.alias_resolution -- Phase 1's hardest problem, exposed as tools.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from farm_core import pipeline
from farm_core.audit import AuditLog

mcp = FastMCP("field-registry")


# Tool functions build one of these, then return its .model_dump() -- see
# mcp_report_export.server for why (a bare Pydantic return type makes
# FastMCP's client-side schema validation reject the refusal shape; a Union
# return type wraps every response in a {"result": ...} envelope). Real
# enforcement happens at construction time, not via the advertised MCP schema.
class SnapshotProvenance(BaseModel):
    data_dir: str
    built_at: str
    source_file_count: int


class CanonicalFieldInfo(BaseModel):
    display_name_by_season: dict[str, str]
    active_seasons: list[int]


class ResolveFieldIdentityResult(BaseModel):
    canonical_fields: dict[str, CanonicalFieldInfo]
    identity_events: list[dict[str, Any]]
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class ResolveFieldNameResult(BaseModel):
    canonical_boundary_name: str
    method: str
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
def resolve_field_identity() -> dict:
    """Return the full resolved canonical field timeline: every canonical
    field's display name by season, and every split/merge/rename/rental-loss
    event, resolved from raw boundary files alone.

    Returns:
        {"canonical_fields": {...}, "identity_events": [...], "provenance": {...}}
    """
    snap = _snapshot()
    _audit_log().log("tool_call", tool="resolve_field_identity")
    payload = snap.identity.to_json()
    return ResolveFieldIdentityResult(**payload, provenance=SnapshotProvenance(**_provenance())).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def resolve_field_name(raw_name: str, season: int) -> dict:
    """Resolve a farmer-visible field name (as it appears in the cost ledger,
    drift and all) for a given season to the stable canonical boundary name.

    Args:
        raw_name: The name as recorded that season (e.g. "north eighty").
        season: The season year the name was recorded in.

    Returns:
        {"canonical_boundary_name": "...", "method": "exact"|"alias",
        "provenance": {...}} on success, or {"error": "...", "code":
        "not_found"} if the name was never recorded in that season.
    """
    snap = _snapshot()
    if season not in snap.seasons:
        return {
            "error": f"unknown season {season}; known seasons are {snap.seasons}",
            "code": "invalid_input",
        }

    active_names = {
        lineage.display_name_by_season.get(season) for lineage in snap.identity.lineages.values()
    }
    if raw_name in active_names:
        resolved, method = raw_name, "exact"
    else:
        resolved = snap.alias_map.get((season, raw_name))
        method = "alias" if resolved else None

    if resolved is None:
        return {
            "error": f"{raw_name!r} was not recorded in season {season}",
            "code": "not_found",
        }

    _audit_log().log("tool_call", tool="resolve_field_name", raw_name=raw_name, season=season)
    return ResolveFieldNameResult(
        canonical_boundary_name=resolved, method=method, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


if __name__ == "__main__":
    mcp.run()
