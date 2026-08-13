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
import dataclasses
import json
from pathlib import Path

from pydantic import ValidationError

from farm_core.audit import AuditLog
from farm_core.pipeline import SEASONS
from farm_model.narrator import narrate_verified
from farm_model.query_parser import ParseFailure, parse_question
from farm_model.query_schema import (
    REQUIRED_FIELDS,
    QueryIntent,
    QueryObject,
    resolve_relative_seasons,
)

from .mcp_client import MCPFleet
from .therefore import build_therefore_line

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


@dataclasses.dataclass(frozen=True)
class AnswerResult:
    """text is always what the CLI prints; ok distinguishes a genuine
    grounded answer from every kind of refusal, so main() can exit non-zero
    without every caller that only cares about the text needing to change.
    """

    text: str
    ok: bool


async def answer_question(
    question: str, audit_log: AuditLog, env_overrides: dict[str, str] | None = None
) -> AnswerResult:
    audit_log.log("query", question=question)

    query = parse_question(question, SEASONS)
    if isinstance(query, ParseFailure):
        audit_log.log("parse_refused", question=question, reason=query.reason, kind=query.kind)
        if query.kind == "model_unreachable":
            return AnswerResult(
                text=(
                    "Couldn't reach the local model -- this isn't about your question, "
                    "something in the setup needs attention. Run `uv run --project host "
                    f"farm-preflight` to see exactly what. ({query.reason})"
                ),
                ok=False,
            )
        return AnswerResult(
            text=(
                "I couldn't map that to a supported lookup -- Precision Farm MCP "
                "only answers retrospective questions about your own recorded "
                f"seasons ({SEASONS[0]}-{SEASONS[-1]}). Reason: {query.reason}"
            ),
            ok=False,
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
        return AnswerResult(text=f"{result['error']} (code: {result.get('code')})", ok=False)

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
    therefore = build_therefore_line(result)
    text = f"{outcome.text}\n\n{therefore}" if therefore else outcome.text
    return AnswerResult(text=text, ok=True)


async def answer_question_structured(
    query: QueryObject, audit_log: AuditLog, env_overrides: dict[str, str] | None = None
) -> AnswerResult:
    """The model-free path (item 4): the caller already knows which intent
    and parameters they want, so there's nothing for Gemma to parse -- and
    nothing to narrate into a sentence either, since a raw structured result
    is exactly what a caller in this position wants back. No ollama.chat
    call happens anywhere in this path (see test_no_ollama_call_in_structured_path).
    Reuses the exact same routing tables, tool call, refusal handling, audit
    events, and "therefore" line as the natural-language path -- only how
    the QueryObject gets built and how the result is presented differ.
    """
    audit_log.log("structured_query", intent=query.intent.value)

    server = _INTENT_TO_SERVER[query.intent]
    tool = _INTENT_TO_TOOL[query.intent]
    args = _tool_args(query)

    async with MCPFleet([server], env_overrides=env_overrides) as fleet:
        tool_result = await fleet.call(server, tool, **args)
    audit_log.log("tool_call", server=server, tool=tool, args=args)

    result = tool_result.data
    if "error" in result:
        audit_log.log("tool_refused", server=server, tool=tool, code=result.get("code"))
        return AnswerResult(text=f"{result['error']} (code: {result.get('code')})", ok=False)

    text = json.dumps(result, indent=2, default=str)
    therefore = build_therefore_line(result)
    if therefore:
        text = f"{text}\n\n{therefore}"
    return AnswerResult(text=text, ok=True)


def _build_structured_query(args: argparse.Namespace) -> QueryObject:
    intent = QueryIntent(args.intent)
    query = QueryObject(
        intent=intent,
        field_name=args.field_name,
        raw_name=args.raw_name,
        season=args.season,
        seasons=args.seasons,
        season_count_from_latest=args.season_count_from_latest,
    )
    if intent == QueryIntent.WHICH_FIELDS_MADE_MONEY:
        # Same deterministic resolution the natural-language path applies in
        # parse_question -- a relative window is never left for a tool to
        # interpret itself.
        query = query.model_copy(update={"seasons": resolve_relative_seasons(query, SEASONS)})
    return query


def _list_intents() -> str:
    lines = ["Available --intent values and their required flags:"]
    for intent, fields in REQUIRED_FIELDS.items():
        if intent == QueryIntent.UNRECOGNIZED:
            continue
        required = ", ".join(f"--{f.replace('_', '-')}" for f in fields) or "(none)"
        lines.append(f"  {intent.value}: {required}")
    lines.append(
        "  which_fields_made_money also accepts --seasons (explicit years) or "
        "--season-count-from-latest (a relative window) instead of nothing"
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="farm-cli",
        description="Precision Farm MCP v1 -- ask a question about your own field records. "
        "Either a free-text question, or --intent for the model-free path (no Ollama "
        "call, raw JSON result) -- see --list-intents.",
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="e.g. 'was the north eighty a bad field or a bad year' "
        "(omit if using --intent instead)",
    )
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_LOG)
    parser.add_argument(
        "--intent",
        choices=[i.value for i in QueryIntent if i != QueryIntent.UNRECOGNIZED],
        help="Model-free path: skip natural-language parsing and narration entirely, "
        "print the raw tool result. Requires this intent's fields -- see --list-intents.",
    )
    parser.add_argument("--field-name")
    parser.add_argument("--raw-name")
    parser.add_argument("--season", type=int)
    parser.add_argument("--seasons", type=int, nargs="+")
    parser.add_argument("--season-count-from-latest", type=int)
    parser.add_argument(
        "--list-intents",
        action="store_true",
        help="Print every --intent value and its required flags, then exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audit_log = AuditLog(args.audit_log)

    if args.list_intents:
        print(_list_intents())
        return 0

    if args.intent:
        try:
            query = _build_structured_query(args)
        except ValidationError as e:
            print(f"Invalid arguments for --intent {args.intent}: {e}")
            return 1
        result = asyncio.run(answer_question_structured(query, audit_log))
        print(result.text)
        return 0 if result.ok else 1

    if not args.question:
        print("Provide a question, or use --intent for the model-free path (see --list-intents).")
        return 1

    question = " ".join(args.question)
    result = asyncio.run(answer_question(question, audit_log))
    print(result.text)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
