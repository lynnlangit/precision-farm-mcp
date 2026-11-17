"""MCP server: canonical field identity and naming-drift alias resolution.
Thin transport wrapper around farm_core.field_identity /
farm_core.alias_resolution -- the hardest problem, exposed as tools.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from farm_core.server_support import (
    SnapshotProvenance,
    audit_log as _audit_log,
    confirmation_guarded as _confirmation_guarded,
    provenance as _provenance,
    snapshot as _snapshot,
)
from farm_core import records_behind as _records

mcp = FastMCP("field-registry")


# Tool functions build one of these, then return its .model_dump() -- see
# mcp_report_export.server for why (a bare Pydantic return type makes
# FastMCP's client-side schema validation reject the refusal shape; a Union
# return type wraps every response in a {"result": ...} envelope). Real
# enforcement happens at construction time, not via the advertised MCP schema.
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
    _audit_log().log("tool_executed", tool="resolve_field_identity")
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

    _audit_log().log("tool_executed", tool="resolve_field_name", raw_name=raw_name, season=season)
    return ResolveFieldNameResult(
        canonical_boundary_name=resolved, method=method, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()



class SourceRecord(BaseModel):
    kind: str
    label: str
    path: str
    tab: str | None
    rows: int
    count_text: str
    which: str


class RecordsBehindResult(BaseModel):
    records: list[SourceRecord]
    provenance: SnapshotProvenance


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def records_behind(
    kinds: list[str], field_name: str | None = None, seasons: list[int] | None = None
) -> dict:
    """List the raw records a lookup read, so a grower can open them and
    check the answer by hand: one entry per file or spreadsheet tab, with
    how many rows matched and which ones (spreadsheet rows, ticket numbers,
    products). Lists records only; computes nothing.

    Args:
        kinds: Which kinds of record, from cost_ledger, unit_prices,
            scale_tickets, yield_monitor, boundaries, as_applied, weather, soil.
        field_name: One field (any spelling the records used), or omit for every field.
        seasons: Season years, or omit for every season.

    Returns:
        {"records": [{"kind", "label", "path", "tab", "rows", "count_text",
        "which"}, ...], "provenance": {...}}, or {"error": "...", "code":
        "not_found" | "invalid_input"}.
    """
    snap = _snapshot()
    try:
        records = _records.records_behind(snap, kinds, field_name=field_name, seasons=seasons)
    except _records.UnknownField as e:
        return {"error": str(e), "code": "not_found"}
    except ValueError as e:
        return {"error": str(e), "code": "invalid_input"}
    _audit_log().log(
        "tool_executed", tool="records_behind", kinds=kinds, field_name=field_name, seasons=seasons
    )
    return RecordsBehindResult(
        records=[SourceRecord(**r) for r in records], provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


if __name__ == "__main__":
    mcp.run()
