"""Single CLI entry point for Precision Farm MCP v1.

    uv run --project host farm-cli "was the north eighty a bad field or a bad year"

Question in -> Gemma parses it into a QueryObject -> the host dispatches to
exactly one of the six MCP servers over stdio -> Gemma narrates the result Gemma never
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
from farm_model.narrator import NarrationOutcome, narrate_verified
from farm_model.query_parser import ParseFailure, parse_question
from farm_model.query_schema import (
    REQUIRED_FIELDS,
    FollowUpContext,
    QueryIntent,
    QueryObject,
    resolve_relative_seasons,
)

from . import __version__
from .mcp_client import MCPFleet, ServerStartTimeout
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
    QueryIntent.SEASON_WEATHER: "weather-history",
    QueryIntent.FIELD_SOIL: "weather-history",
    QueryIntent.APPLIED_INPUTS: "as-applied",
    QueryIntent.NITROGEN_HISTORY: "as-applied",
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
    QueryIntent.SEASON_WEATHER: "get_season_weather",
    QueryIntent.FIELD_SOIL: "get_field_soil",
    QueryIntent.APPLIED_INPUTS: "get_applied_inputs",
    QueryIntent.NITROGEN_HISTORY: "get_nitrogen_history",
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
    if query.intent == QueryIntent.SEASON_WEATHER:
        return {"season": query.season}
    if query.intent in (QueryIntent.FIELD_SOIL, QueryIntent.NITROGEN_HISTORY):
        return {"field_name": query.field_name}
    if query.intent in (
        QueryIntent.APPLIED_INPUTS,
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
    # Optional structured detail for richer front ends (the grower web app in
    # web/). The CLI only ever prints `text`; every field below defaults to
    # None so existing callers and tests are unaffected.
    query: QueryObject | None = None
    server: str | None = None
    tool: str | None = None
    tool_args: dict | None = None
    payload: dict | None = None
    narration: NarrationOutcome | None = None
    therefore: str | None = None
    # "model_unreachable", "unparseable", "unresolved_followup" or "tool_refused"
    # when ok is False.
    refusal_kind: str | None = None


async def answer_question(
    question: str,
    audit_log: AuditLog,
    env_overrides: dict[str, str] | None = None,
    context: FollowUpContext | None = None,
    fleet: MCPFleet | None = None,
) -> AnswerResult:
    """`context` is set only for a follow-up (the grower web app): the last
    verified answer's field, season and question type. It only helps parse
    the question -- the lookup, verification and narration below are exactly
    the same as for a first question, and the narrator never sees it.

    `fleet` is an already-running set of servers (the web app keeps one open
    so each question skips the server start and snapshot build). Without it,
    the needed server is started for this one question, as the CLI does.
    """
    if context is not None and context.is_empty():
        context = None
    if context is None:
        audit_log.log("query", question=question)
    else:
        audit_log.log(
            "query", question=question, follow_up_context=context.model_dump(mode="json")
        )

    # A first question calls the parser exactly as before; only a follow-up
    # passes the extra context.
    query = (
        parse_question(question, SEASONS)
        if context is None
        else parse_question(question, SEASONS, context=context)
    )
    if isinstance(query, ParseFailure):
        audit_log.log("parse_refused", question=question, reason=query.reason, kind=query.kind)
        if query.kind == "unresolved_followup":
            return AnswerResult(
                text=(
                    "I wasn't sure which field or season you meant, so I didn't look "
                    "anything up. Try naming both, e.g. \"Does the seed cost on "
                    f"Sheyenne Bottom in 2023 look right?\" (Reason: {query.reason})"
                ),
                ok=False,
                refusal_kind="unresolved_followup",
            )
        if query.kind == "model_unreachable":
            return AnswerResult(
                text=(
                    "Couldn't reach the local model -- this isn't about your question, "
                    "something in the setup needs attention. Run `uv run --project host "
                    f"farm-preflight` to see exactly what. ({query.reason})"
                ),
                ok=False,
                refusal_kind="model_unreachable",
            )
        return AnswerResult(
            text=(
                "I couldn't map that to a supported lookup -- Precision Farm MCP "
                "only answers retrospective questions about your own recorded "
                f"seasons ({SEASONS[0]}-{SEASONS[-1]}). I can look up records, but I "
                "can't explain terms or numbers yet. Try asking about a field and "
                "season, e.g. \"Was East 80 a bad field or a bad year?\" "
                f"(Reason: {query.reason})"
            ),
            ok=False,
            refusal_kind="unparseable",
        )

    # What the parser decided, before routing -- lets the eval runner (and a
    # reader of the audit log) check the intent and parameters directly.
    audit_log.log(
        "parsed",
        intent=query.intent.value,
        field_name=query.field_name,
        raw_name=query.raw_name,
        season=query.season,
        seasons=query.seasons,
        season_count_from_latest=query.season_count_from_latest,
    )

    server = _INTENT_TO_SERVER[query.intent]
    tool = _INTENT_TO_TOOL[query.intent]
    args = _tool_args(query)

    if fleet is not None:
        tool_result = await fleet.call(server, tool, **args)
    else:
        async with MCPFleet([server], env_overrides=env_overrides) as one_off:
            tool_result = await one_off.call(server, tool, **args)
    audit_log.log("tool_call", server=server, tool=tool, args=args)

    result = tool_result.data
    if "error" in result:
        audit_log.log("tool_refused", server=server, tool=tool, code=result.get("code"))
        return AnswerResult(
            text=f"{result['error']} (code: {result.get('code')})",
            ok=False,
            query=query,
            server=server,
            tool=tool,
            tool_args=args,
            payload=result,
            refusal_kind="tool_refused",
        )

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
        failed_checks=[list(f) for f in outcome.failed_checks],
        rejected_texts=list(outcome.rejected_texts),
        model_context_shown=outcome.context is not None,
    )
    therefore = build_therefore_line(result)
    text = f"{outcome.text}\n\n{therefore}" if therefore else outcome.text
    return AnswerResult(
        text=text,
        ok=True,
        query=query,
        server=server,
        tool=tool,
        tool_args=args,
        payload=result,
        narration=outcome,
        therefore=therefore,
    )


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
        description=f"Precision Farm MCP {__version__} -- ask a question about your own field records. "
        "Either a free-text question, or --intent for the model-free path (no Ollama "
        "call, raw JSON result) -- see --list-intents.",
    )
    parser.add_argument(
        "--version", action="version", version=f"Precision Farm MCP {__version__}"
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
    # Servers write their tool_executed events to FARM_AUDIT_LOG; point them at
    # the same file so --audit-log captures the whole question in one chain.
    server_env = {"FARM_AUDIT_LOG": str(Path(args.audit_log).resolve())}

    if args.list_intents:
        print(_list_intents())
        return 0

    if args.intent:
        try:
            query = _build_structured_query(args)
        except ValidationError as e:
            print(f"Invalid arguments for --intent {args.intent}: {e}")
            return 1
        try:
            result = asyncio.run(answer_question_structured(query, audit_log, env_overrides=server_env))
        except ServerStartTimeout as e:
            print(e)
            return 1
        print(result.text)
        return 0 if result.ok else 1

    # argv [""] (e.g. `farm-cli ""`) is a non-empty list, so check the joined
    # text: a blank or whitespace-only question never reaches the model.
    question = " ".join(args.question).strip()
    if not question:
        print("Provide a question, or use --intent for the model-free path (see --list-intents).")
        return 1

    try:
        result = asyncio.run(answer_question(question, audit_log, env_overrides=server_env))
    except ServerStartTimeout as e:
        print(e)
        return 1
    print(result.text)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
