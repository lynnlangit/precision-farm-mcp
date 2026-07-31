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
from farm_core.expectation import AttributionUnavailable
from farm_core.expectation import compute_attribution as _compute_attribution
from farm_core.profitability import bad_field_or_bad_year as _bad_field_or_bad_year
from farm_core.profitability import which_fields_made_money as _which_fields_made_money
from farm_core.zone_profitability import ZoneProfitabilityUnavailable
from farm_core.zone_profitability import (
    compute_zone_profitability as _compute_zone_profitability,
)
from farm_core.zone_profitability import (
    unprofitable_zones_in_profitable_fields as _unprofitable_zones_in_profitable_fields,
)

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
    """`modeled.attribution` is populated only for a `bad_year` verdict --
    one entry per outlier season, each Phase C's weather/soil expectation
    model (farm_core.expectation) decomposing that season's shortfall into
    a weather-driven `season_effect` and an unexplained `residual`. The
    `verdict` itself is unchanged by this: it's a purely statistical
    classification that needs no weather data and stays the primary
    answer; attribution only ever supplements it, never replaces it.
    """

    canonical_id: str
    verdict: str
    evidence: dict[str, Any]
    field_name: str
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class ZoneEntry(BaseModel):
    zone_index: int
    acres: float
    available: bool
    point_count: int
    yield_bu_ac: float | None = None
    revenue: float | None = None
    cost: float | None = None
    profit: float | None = None
    unavailable_reason: str | None = None


class ZoneProfitabilityResult(BaseModel):
    """Derived arithmetic (Phase D), not modeled -- zone cost reuses the
    field's own authoritative $/acre uniformly (see farm_core.
    zone_profitability's module docstring for why: cost has no spatial
    resolution anywhere in this data model), only yield is actually
    zone-resolved. `modeled` is reserved but never populated here.
    """

    canonical_id: str
    season: int
    field_name: str
    field_acres: float
    field_profit: float
    zones: list[ZoneEntry]
    provenance: SnapshotProvenance
    modeled: dict[str, Any] | None = None


class UnprofitableZonesSummaryResult(BaseModel):
    seasons_examined: list[int]
    field_seasons_examined: int
    acres_examined: float
    acres_unprofitable: float
    pct_acres_unprofitable_in_profitable_fields: float | None
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

    modeled = None
    outlier_seasons = result.get("evidence", {}).get("outlier_seasons")
    if result.get("verdict") == "bad_year" and outlier_seasons:
        attributions = []
        for outlier_season in outlier_seasons:
            try:
                attribution = _compute_attribution(snap, canonical_id, outlier_season)
            except AttributionUnavailable:
                continue
            attributions.append({"season": outlier_season, **attribution.to_json()})
        if attributions:
            modeled = {"attribution": attributions}

    return BadFieldOrBadYearResult(
        **result,
        field_name=current_name,
        provenance=SnapshotProvenance(**_provenance()),
        modeled=modeled,
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def zone_profitability(field_name: str, season: int) -> dict:
    """Grid a field into a 2x2 set of management zones and compute
    per-zone profit -- surfaces a shortfall that's invisible in the
    field-level total because other zones compensate for it.

    Args:
        field_name: The farmer-visible field name, current or historical.
        season: The season year. Only available for seasons with
            as-applied input-log coverage (the newest few seasons) --
            cost has no spatial resolution to derive zone cost from
            otherwise.

    Returns:
        {"zones": [...], "field_profit": ..., "provenance": {...}} on
        success, or {"error": "...", "code": "not_found"} for an
        unrecognized field name, or {"error": "...", "code":
        "invalid_input"} for a season without as-applied coverage. A
        zone with too few yield-monitor points to compute reliably is
        included with `"available": false`, never estimated.
    """
    snap = _snapshot()
    canonical_id = snap.canonical_id_for_name(field_name)
    if canonical_id is None:
        return {
            "error": f"no field named {field_name!r} was found in the record",
            "code": "not_found",
        }

    try:
        result = _compute_zone_profitability(snap, canonical_id, season)
    except ZoneProfitabilityUnavailable as e:
        return {"error": e.reason, "code": "invalid_input"}

    _audit_log().log(
        "tool_call", tool="zone_profitability", field_name=field_name, season=season
    )
    current_name = snap.identity.lineages[canonical_id].display_name_by_season[
        max(snap.identity.lineages[canonical_id].active_seasons)
    ]
    return ZoneProfitabilityResult(
        canonical_id=result.canonical_id,
        season=result.season,
        field_name=current_name,
        field_acres=result.field_acres,
        field_profit=result.field_profit,
        zones=[ZoneEntry(**z.to_json()) for z in result.zones],
        provenance=SnapshotProvenance(**_provenance()),
    ).model_dump()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@_confirmation_guarded
def unprofitable_zones_in_profitable_fields() -> dict:
    """The headline zone-profitability figure: across every field/season
    that was genuinely profitable overall, what share of its acres sat
    in a zone with negative zone-level profit anyway.

    Returns:
        {"pct_acres_unprofitable_in_profitable_fields": ..., "acres_examined":
        ..., "acres_unprofitable": ..., "provenance": {...}}.
        `pct_acres_unprofitable_in_profitable_fields` is null (not 0) if no
        acres were examinable at all.
    """
    snap = _snapshot()
    summary = _unprofitable_zones_in_profitable_fields(snap)
    _audit_log().log("tool_call", tool="unprofitable_zones_in_profitable_fields")
    return UnprofitableZonesSummaryResult(
        **summary, provenance=SnapshotProvenance(**_provenance())
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
