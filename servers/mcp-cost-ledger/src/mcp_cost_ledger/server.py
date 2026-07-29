"""MCP server: the farmer's cost ledger, resolved through the naming-drift
alias table, plus cost-ledger-vs-as-applied reconciliation. Thin transport
wrapper around farm_core.reconciliation.reconcile_cost_ledger_vs_as_applied.
"""

from __future__ import annotations

import dataclasses
import functools
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from farm_core import pipeline
from farm_core.audit import AuditLog
from farm_core.reconciliation import reconcile_cost_ledger_vs_as_applied

mcp = FastMCP("cost-ledger")

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
def _cost_reconciliation():
    snap = _snapshot()
    return reconcile_cost_ledger_vs_as_applied(snap.con, snap.alias_map)


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


def _provenance(mapping_version: str | None = None) -> dict[str, Any]:
    snap = _snapshot()
    prov: dict[str, Any] = {
        "data_dir": str(snap.data_dir),
        "built_at": snap.built_at,
        "source_file_count": len(snap.source_files),
    }
    if mapping_version is not None:
        prov["mapping_version"] = mapping_version
    return prov


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_cost_ledger_row(field_name: str, season: int) -> dict:
    """Fetch the farmer's recorded per-acre costs for one field/season,
    resolved through the naming-drift alias table (the ledger's own spelling
    that season may differ from the stable boundary name).

    Args:
        field_name: The stable boundary field name.
        season: The season year.

    Returns:
        Seed/fertilizer/chemical/fuel/cash-rent $/ac plus the original cost
        basis and mapping version, or {"error": "...", "code": "not_found"}.
    """
    snap = _snapshot()
    row = snap.con.execute(
        "SELECT raw_field_name, seed_cost_per_ac, fertilizer_cost_per_ac, chemical_cost_per_ac, "
        "fuel_cost_per_ac, cash_rent_per_ac, cost_basis, mapping_version, notes "
        "FROM cost_ledger_rows WHERE season = ?",
        [season],
    ).fetchall()
    match = next((r for r in row if snap.alias_map.get((season, r[0]), r[0]) == field_name), None)
    if match is None:
        return {
            "error": f"no cost ledger row for {field_name!r} in season {season}",
            "code": "not_found",
        }

    _audit_log().log("tool_call", tool="get_cost_ledger_row", field_name=field_name, season=season)
    return {
        "field_name": field_name,
        "seed_cost_per_ac": match[1],
        "fertilizer_cost_per_ac": match[2],
        "chemical_cost_per_ac": match[3],
        "fuel_cost_per_ac": match[4],
        "cash_rent_per_ac": match[5],
        "cost_basis": match[6],
        "notes": match[8],
        "provenance": _provenance(mapping_version=match[7]),
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def get_cost_reconciliation(field_name: str, season: int) -> dict:
    """Reconcile the ledger's seed and fertilizer $/ac against what the
    as-applied logs plus unit prices imply, for seasons where both exist
    (the newest four).

    Args:
        field_name: The stable boundary field name.
        season: The season year.

    Returns:
        {"results": [<seed line item>, <fertilizer line item>], "provenance":
        {...}}. An empty results list means no as-applied data exists that
        season (not an error).
    """
    snap = _snapshot()
    if season not in snap.seasons:
        return {
            "error": f"unknown season {season}; known seasons are {snap.seasons}",
            "code": "invalid_input",
        }
    _audit_log().log(
        "tool_call", tool="get_cost_reconciliation", field_name=field_name, season=season
    )
    results = [
        dataclasses.asdict(r)
        for r in _cost_reconciliation()
        if r.field_name == field_name and r.season == season
    ]
    return {"results": results, "provenance": _provenance()}


if __name__ == "__main__":
    mcp.run()
