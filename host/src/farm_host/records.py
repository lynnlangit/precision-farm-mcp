"""Which raw records each lookup reads, so the web app can list the exact
files, spreadsheet tabs and rows behind an answer ("Show the records").

The list comes from field-registry's read-only `records_behind` tool. It is
fetched after the answer is checked and never reaches the narrator or the
checks: it is for the grower, not the AI.
"""

from __future__ import annotations

# Kinds of record each tool reads (see farm_core.records_behind.KINDS and
# the farm_core module each tool calls).
_PROFIT = ["cost_ledger", "scale_tickets", "boundaries"]
_ZONES = [*_PROFIT, "yield_monitor", "as_applied"]

SOURCES_BY_TOOL: dict[str, list[str]] = {
    "which_fields_made_money": _PROFIT,
    "bad_field_or_bad_year": _PROFIT,
    "zone_profitability": _ZONES,
    "unprofitable_zones_in_profitable_fields": _ZONES,
    "resolve_field_name": ["cost_ledger", "boundaries"],
    "get_yield_reconciliation": ["yield_monitor", "scale_tickets", "boundaries"],
    "get_cost_reconciliation": ["cost_ledger", "unit_prices", "as_applied", "boundaries"],
    "get_season_weather": ["weather"],
    "get_field_soil": ["soil"],
    "get_applied_inputs": ["as_applied"],
    "get_nitrogen_history": ["as_applied"],
}


def records_request(tool: str, args: dict, payload: dict) -> dict | None:
    """Arguments for `records_behind` for this lookup, or None if the tool
    isn't one we know the records for."""
    kinds = SOURCES_BY_TOOL.get(tool)
    if kinds is None:
        return None
    kinds = list(kinds)
    field_name = args.get("field_name") or args.get("raw_name")
    if "seasons" in args:
        seasons = args["seasons"]
    elif "season" in args:
        seasons = [args["season"]]
    else:
        seasons = None

    if tool == "bad_field_or_bad_year":
        # A bad-year verdict adds a modeled weather/soil estimate for the
        # outlier season(s), so those records are read too.
        attribution = ((payload.get("modeled") or {}).get("attribution")) or []
        if attribution:
            kinds += ["weather", "soil"]
    request: dict = {"kinds": kinds}
    if field_name:
        request["field_name"] = field_name
    if seasons is not None:
        request["seasons"] = seasons
    return request
