"""MCP server: yield history and yield-monitor-vs-scale-ticket reconciliation.
Thin transport wrapper around farm_core.reconciliation.reconcile_yield_vs_scale.
"""

from __future__ import annotations

import dataclasses
import functools
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from farm_core import pipeline
from farm_core.audit import AuditLog
from farm_core.reconciliation import reconcile_yield_vs_scale

mcp = FastMCP("yield-history")


# Tool functions build one of these, then return its .model_dump() -- see
# mcp_report_export.server for why (a bare Pydantic return type makes
# FastMCP's client-side schema validation reject the refusal shape; a Union
# return type wraps every response in a {"result": ...} envelope). Real
# enforcement happens at construction time, not via the advertised MCP schema.
class SnapshotProvenance(BaseModel):
    data_dir: str
    built_at: str
    source_file_count: int


class YieldReconciliationEntry(BaseModel):
    field_name: str
    season: int
    scale_total_bu: float
    monitor_total_bu: float | None
    pct_diff: float | None
    totals_discrepancy: bool
    coverage_gap_bins: int | None
    coverage_gap_flagged: bool
    note: str


class YieldReconciliationResult(YieldReconciliationEntry):
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class ListYieldReconciliationResult(BaseModel):
    results: list[YieldReconciliationEntry]
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
def _reconciliation():
    return reconcile_yield_vs_scale(_snapshot().con)


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
def get_yield_reconciliation(field_name: str, season: int) -> dict:
    """Reconcile yield-monitor totals against scale-ticket totals for one
    field/season, and check yield-monitor spatial coverage for gaps.

    Args:
        field_name: The stable boundary field name (not a ledger alias).
        season: The season year.

    Returns:
        Both totals, the percent difference, and coverage-gap status on
        success, or {"error": "...", "code": "not_found"} if there's no
        scale-ticket record for that field/season.
    """
    match = next(
        (r for r in _reconciliation() if r.field_name == field_name and r.season == season),
        None,
    )
    if match is None:
        return {
            "error": f"no scale-ticket record for {field_name!r} in season {season}",
            "code": "not_found",
        }
    _audit_log().log(
        "tool_call", tool="get_yield_reconciliation", field_name=field_name, season=season
    )
    return YieldReconciliationResult(
        **dataclasses.asdict(match), provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def list_yield_reconciliation(season: int) -> dict:
    """List the yield reconciliation result for every field active in a season.

    Args:
        season: The season year.

    Returns:
        {"results": [...], "provenance": {...}}, or {"error": "...", "code":
        "invalid_input"} for an unrecognized season.
    """
    snap = _snapshot()
    if season not in snap.seasons:
        return {
            "error": f"unknown season {season}; known seasons are {snap.seasons}",
            "code": "invalid_input",
        }
    _audit_log().log("tool_call", tool="list_yield_reconciliation", season=season)
    results = [dataclasses.asdict(r) for r in _reconciliation() if r.season == season]
    return ListYieldReconciliationResult(
        results=results, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


if __name__ == "__main__":
    mcp.run()
