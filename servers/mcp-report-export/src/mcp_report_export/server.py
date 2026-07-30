"""MCP server: profitability queries and redacted export. The "1 new" server
in the v1 architecture -- it doesn't wrap an existing precision-medicine-mcp
server, it's modeled on mcp-deidentify's redaction-tool shape instead.

All arithmetic here is a thin pass-through to farm_core.profitability --
this server adds MCP transport (Pydantic I/O, readOnlyHint, structured
refusals) around it, nothing more. That's the point of Phase 4: wrapping in
the protocol must not change a single number.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from farm_core import governance, pipeline
from farm_core.audit import AuditLog
from farm_core.profitability import bad_field_or_bad_year as _bad_field_or_bad_year
from farm_core.profitability import which_fields_made_money as _which_fields_made_money

mcp = FastMCP("report-export")


# Tool functions build one of these, then return its .model_dump() -- not the
# model instance itself, and not `Model | dict` as the declared return type.
# Verified empirically: a bare Pydantic return type makes FastMCP's client-side
# schema validation reject the {"error", "code"} refusal shape, and a Union
# return type makes FastMCP wrap every response in a {"result": ...} envelope
# (x-fastmcp-wrap-result), breaking every existing caller's direct-key access.
# Returning .model_dump() from a function still annotated -> dict sidesteps
# both: the wire shape is unchanged, and real enforcement happens at
# construction time (a missing required field raises ValidationError inside
# the tool function, before serialization), not via the advertised MCP schema.
class SnapshotProvenance(BaseModel):
    data_dir: str
    built_at: str
    source_file_count: int


class FieldProfitResult(BaseModel):
    canonical_id: str
    display_name: str
    seasons: list[int]
    total_profit: float
    total_revenue: float
    total_cost: float


class WhichFieldsMadeMoneyResult(BaseModel):
    """`modeled` is reserved for Phase C's future model output (e.g. a
    weather-attributed decomposition of a shortfall) -- see A2/A3 in
    docs/plans. Nothing populates it yet; every value above is measured or
    derived. Keeping the field on every response now (rather than adding it
    only when Phase C needs it) means a modeled value can only ever end up
    somewhere other than here by a reviewable authoring mistake, not a
    silent tagging omission.
    """

    results: list[FieldProfitResult]
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class BadFieldOrBadYearResult(BaseModel):
    canonical_id: str
    verdict: str
    evidence: dict[str, Any]
    field_name: str
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class ExportProfitabilityResult(BaseModel):
    exported_to: str
    redacted: bool
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
def which_fields_made_money(seasons: list[int]) -> dict:
    """Rank every canonical field lineage by total profit across the given seasons.

    Args:
        seasons: Season years to include, e.g. [2021, 2022, 2023, 2024, 2025].

    Returns:
        {"results": [...], "provenance": {...}} on success, or
        {"error": "...", "code": "invalid_input"} if seasons is empty or
        contains a year outside the generator's range.
    """
    snap = _snapshot()
    if not seasons:
        return {"error": "seasons must be a non-empty list", "code": "invalid_input"}
    unknown = [s for s in seasons if s not in snap.seasons]
    if unknown:
        return {
            "error": f"unknown season(s) {unknown}; known seasons are {snap.seasons}",
            "code": "invalid_input",
        }

    _audit_log().log("tool_call", tool="which_fields_made_money", seasons=seasons)
    results = _which_fields_made_money(snap.profit_records, seasons)
    return WhichFieldsMadeMoneyResult(
        results=results, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def bad_field_or_bad_year(field_name: str) -> dict:
    """Classify a field's profit history as a chronically bad field, a single
    bad year, or consistently profitable.

    Args:
        field_name: The farmer-visible field name, current or historical
            (e.g. "Marginal Eighty").

    Returns:
        The classification and evidence on success, or
        {"error": "...", "code": "not_found"} if the name was never used by
        any field in the record.
    """
    snap = _snapshot()
    canonical_id = snap.canonical_id_for_name(field_name)
    if canonical_id is None:
        return {
            "error": f"no field named {field_name!r} was found in the record",
            "code": "not_found",
        }

    _audit_log().log("tool_call", tool="bad_field_or_bad_year", field_name=field_name)
    result = _bad_field_or_bad_year(snap.profit_records, canonical_id)
    current_name = snap.identity.lineages[canonical_id].display_name_by_season[
        max(snap.identity.lineages[canonical_id].active_seasons)
    ]
    return BadFieldOrBadYearResult(
        **result, field_name=current_name, provenance=SnapshotProvenance(**_provenance())
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
@_confirmation_guarded
def export_profitability(
    path: str,
    seasons: list[int] | None = None,
    allow_write: bool = False,
    allow_identifying: bool = False,
) -> dict:
    """Export profitability results to a JSON file. Read-only by default --
    this refuses unless allow_write=True is passed explicitly. Redacted by
    default -- coordinates and grower-identity fields are stripped from the
    export unless allow_identifying=True is passed explicitly.

    Args:
        path: Destination file path.
        seasons: Seasons to include; defaults to every season in the record.
        allow_write: Must be True or the export is refused.
        allow_identifying: Must be True to include identifying fields (none
            are present in profitability output today, but the flag is
            honored for forward compatibility with richer exports).

    Returns:
        {"exported_to": path, "redacted": bool} on success, or
        {"error": "...", "code": "write_not_allowed"} if allow_write is False.
    """
    snap = _snapshot()
    use_seasons = seasons if seasons is not None else snap.seasons
    host = governance.HostConfig(allow_write=allow_write)

    try:
        results = _which_fields_made_money(snap.profit_records, use_seasons)
        governance.export_json(
            {"results": results, "provenance": _provenance()},
            Path(path),
            host,
            _audit_log(),
            allow_identifying=allow_identifying,
        )
    except governance.WriteNotAllowed as e:
        return {"error": str(e), "code": "write_not_allowed"}

    return ExportProfitabilityResult(exported_to=path, redacted=not allow_identifying).model_dump()


if __name__ == "__main__":
    mcp.run()
