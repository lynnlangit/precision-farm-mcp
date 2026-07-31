"""Single CLI entry point for Precision Farm MCP v1.

    uv run --project host farm-cli "was the north eighty a bad field or a bad year"

Question in -> Gemma parses it into a QueryObject -> the host dispatches to
exactly one MCP server over stdio -> Gemma narrates the result Gemma never
computed. Every step is logged to an append-only audit trail. Read-only:
there is no write path reachable from this CLI at all.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from farm_core.audit import AuditLog
from farm_core.pipeline import SEASONS
from farm_model.narrator import narrate_verified
from farm_model.query_parser import ParseFailure, parse_question
from farm_model.query_schema import QueryIntent, QueryObject

from .mcp_client import MCPFleet

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_LOG = REPO_ROOT / "data" / "audit.jsonl"

_INTENT_TO_SERVER: dict[QueryIntent, str] = {
    QueryIntent.WHICH_FIELDS_MADE_MONEY: "report-export",
    QueryIntent.BAD_FIELD_OR_BAD_YEAR: "report-export",
    QueryIntent.EXPLAIN_SHORTFALL: "report-export",
    QueryIntent.ZONE_PROFITABILITY: "report-export",
    QueryIntent.UNPROFITABLE_ZONES_IN_PROFITABLE_FIELDS: "report-export",
    QueryIntent.RESOLVE_FIELD_NAME: "field-registry",
    QueryIntent.YIELD_RECONCILIATION: "yield-history",
    QueryIntent.COST_RECONCILIATION: "cost-ledger",
}

_INTENT_TO_TOOL: dict[QueryIntent, str] = {
    QueryIntent.WHICH_FIELDS_MADE_MONEY: "which_fields_made_money",
    QueryIntent.BAD_FIELD_OR_BAD_YEAR: "bad_field_or_bad_year",
    # Same underlying tool as bad_field_or_bad_year -- once C4 lands, its
    # response already carries modeled.attribution, so "why was X a bad
    # year" and "was X a bad field or a bad year" are the same lookup,
    # just recognized as different question shapes at the parsing layer.
    QueryIntent.EXPLAIN_SHORTFALL: "bad_field_or_bad_year",
    QueryIntent.ZONE_PROFITABILITY: "zone_profitability",
    QueryIntent.UNPROFITABLE_ZONES_IN_PROFITABLE_FIELDS: "unprofitable_zones_in_profitable_fields",
    QueryIntent.RESOLVE_FIELD_NAME: "resolve_field_name",
    QueryIntent.YIELD_RECONCILIATION: "get_yield_reconciliation",
    QueryIntent.COST_RECONCILIATION: "get_cost_reconciliation",
}


def _tool_args(query: QueryObject) -> dict:
    if query.intent == QueryIntent.WHICH_FIELDS_MADE_MONEY:
        return {"seasons": query.seasons}
    if query.intent in (QueryIntent.BAD_FIELD_OR_BAD_YEAR, QueryIntent.EXPLAIN_SHORTFALL):
        return {"field_name": query.field_name}
    if query.intent == QueryIntent.UNPROFITABLE_ZONES_IN_PROFITABLE_FIELDS:
        return {}
    if query.intent == QueryIntent.RESOLVE_FIELD_NAME:
        return {"raw_name": query.raw_name, "season": query.season}
    if query.intent in (
        QueryIntent.YIELD_RECONCILIATION,
        QueryIntent.COST_RECONCILIATION,
        QueryIntent.ZONE_PROFITABILITY,
    ):
        return {"field_name": query.field_name, "season": query.season}
    raise ValueError(f"no tool mapping for intent {query.intent!r}")  # pragma: no cover


async def answer_question(
    question: str, audit_log: AuditLog, env_overrides: dict[str, str] | None = None
) -> str:
    audit_log.log("query", question=question)

    query = parse_question(question, SEASONS)
    if isinstance(query, ParseFailure):
        audit_log.log("parse_refused", question=question, reason=query.reason)
        return (
            "I couldn't map that to a supported lookup -- Precision Farm MCP "
            "only answers retrospective questions about your own recorded "
            f"seasons ({SEASONS[0]}-{SEASONS[-1]}). Reason: {query.reason}"
        )

    server = _INTENT_TO_SERVER[query.intent]
    tool = _INTENT_TO_TOOL[query.intent]
    args = _tool_args(query)

    async with MCPFleet([server], env_overrides=env_overrides) as fleet:
        tool_result = await fleet.call(server, tool, **args)
    audit_log.log("tool_call", server=server, tool=tool, args=args)

    result = tool_result.data
    if "error" in result:
        audit_log.log("tool_refused", server=server, tool=tool, code=result.get("code"))
        return f"{result['error']} (code: {result.get('code')})"

    outcome = narrate_verified(question, result, untrusted_paths=tool_result.untrusted_paths)
    if outcome.truncated:
        audit_log.log("payload_truncated", server=server, tool=tool)
    audit_log.log(
        "narration",
        question=question,
        grounded=outcome.measured_or_derived_grounding.is_grounded,
        modeled_grounded=(
            outcome.modeled_grounding.is_grounded if outcome.modeled_grounding else None
        ),
        attempts=outcome.attempts_used,
        used_fallback=outcome.used_fallback,
    )
    return outcome.text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="farm-cli",
        description="Precision Farm MCP v1 -- ask a question about your own field records.",
    )
    parser.add_argument(
        "question", nargs="+", help="e.g. 'was the north eighty a bad field or a bad year'"
    )
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_LOG)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    question = " ".join(args.question)
    audit_log = AuditLog(args.audit_log)
    answer = asyncio.run(answer_question(question, audit_log))
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
