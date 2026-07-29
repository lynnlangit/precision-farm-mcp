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

from farm_core.audit import AuditLog
from farm_core.pipeline import build_farm_snapshot

mcp = FastMCP("as-applied")

_REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = Path(os.getenv("FARM_DATA_DIR", str(_REPO_ROOT / "data" / "synthetic")))
AUDIT_LOG_PATH = Path(os.getenv("FARM_AUDIT_LOG", str(_REPO_ROOT / "data" / "audit.jsonl")))


@functools.lru_cache(maxsize=1)
def _snapshot():
    return build_farm_snapshot(DATA_DIR)


@functools.lru_cache(maxsize=1)
def _audit_log() -> AuditLog:
    return AuditLog(AUDIT_LOG_PATH)


def _provenance() -> dict[str, Any]:
    snap = _snapshot()
    return {
        "data_dir": str(snap.data_dir),
        "built_at": snap.built_at,
        "source_file_count": len(snap.source_files),
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
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
        "tool_call", tool="get_as_applied_events", field_name=field_name, season=season
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
    return {"events": events, "provenance": _provenance()}


if __name__ == "__main__":
    mcp.run()
