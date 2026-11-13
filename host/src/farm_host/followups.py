"""Follow-up questions for the grower web app, without a chat history.

Three small, model-free pieces:

- next_context: what a follow-up carries forward -- the field, season and
  question type of the last *verified* answer, nothing else. A refusal never
  changes it, and no earlier answer's numbers are ever kept.
- resolved_label: the "Showing: East 80 . 2020 . ..." line shown above each
  answer, so a grower can see which question was actually answered.
- suggest_followups: 2-3 fully spelled-out next questions, built from the
  verified result by fixed templates. Each one names its field and season, so
  it goes through the same parse -> lookup -> verify path as a typed question.
"""

from __future__ import annotations

from farm_core.pipeline import SEASONS
from farm_model.query_schema import FollowUpContext, QueryIntent

from .cli import AnswerResult

MAX_SUGGESTIONS = 3

# Zone profit and cost reconciliation need as-applied logs, which the
# generator writes for the newest four seasons only (as_applied_seasons_count).
# Used only to avoid *suggesting* a lookup that would be refused; the tools
# still decide, from the data, what they can answer.
_AS_APPLIED_SEASONS = frozenset(SEASONS[-4:])

TOPIC_LABELS: dict[QueryIntent, str] = {
    QueryIntent.WHICH_FIELDS_MADE_MONEY: "which fields made money",
    QueryIntent.BAD_FIELD_OR_BAD_YEAR: "bad field or bad year",
    QueryIntent.EXPLAIN_SHORTFALL: "why it was a bad year",
    QueryIntent.ZONE_PROFITABILITY: "profit by zone",
    QueryIntent.UNPROFITABLE_ZONES_IN_PROFITABLE_FIELDS: "losing zones in profitable fields",
    QueryIntent.RESOLVE_FIELD_NAME: "what a field name refers to",
    QueryIntent.YIELD_RECONCILIATION: "yield monitor vs scale tickets",
    QueryIntent.COST_RECONCILIATION: "ledger costs vs as-applied costs",
    QueryIntent.SEASON_WEATHER: "season rain and heat",
    QueryIntent.FIELD_SOIL: "soil water capacity",
    QueryIntent.APPLIED_INPUTS: "what was applied",
    QueryIntent.NITROGEN_HISTORY: "nitrogen across seasons",
}


def _record_field_name(result: AnswerResult) -> str | None:
    """The field name as the records spell it, from the verified payload."""
    payload = result.payload or {}
    if isinstance(payload.get("canonical_boundary_name"), str):
        return payload["canonical_boundary_name"]
    if isinstance(payload.get("field_name"), str):
        return payload["field_name"]
    rows = payload.get("results")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        names = {r.get("field_name") for r in rows}
        if len(names) == 1 and isinstance(rows[0].get("field_name"), str):
            return rows[0]["field_name"]
    return None


def next_context(result: AnswerResult, previous: FollowUpContext | None) -> FollowUpContext | None:
    """The context the *next* question carries. Only a verified answer moves it."""
    query = result.query
    if not result.ok or query is None:
        return previous
    prev = previous or FollowUpContext()
    field = _record_field_name(result) or query.field_name or prev.field_name
    if query.season is not None:
        season = query.season
    elif query.seasons and len(query.seasons) == 1:
        season = query.seasons[0]
    else:
        season = prev.season
    return FollowUpContext(field_name=field, season=season, intent=query.intent)


def _seasons_text(seasons: list[int]) -> str:
    s = sorted(seasons)
    if len(s) > 2 and s == list(range(s[0], s[-1] + 1)):
        return f"{s[0]}–{s[-1]}"
    return ", ".join(str(x) for x in s)


def resolved_label(result: AnswerResult) -> str | None:
    """'East 80 . 2020 . yield monitor vs scale tickets': what was looked up."""
    query = result.query
    if query is None:
        return None
    args = result.tool_args or {}
    parts: list[str] = []
    if args.get("raw_name"):
        parts.append(f"“{args['raw_name']}”")
    elif args.get("field_name"):
        parts.append(str(args["field_name"]))
    if args.get("season") is not None:
        parts.append(str(args["season"]))
    elif args.get("seasons"):
        parts.append(_seasons_text(args["seasons"]))
    elif query.intent in (QueryIntent.BAD_FIELD_OR_BAD_YEAR, QueryIntent.EXPLAIN_SHORTFALL):
        parts.append("every season on record")
    elif query.intent == QueryIntent.UNPROFITABLE_ZONES_IN_PROFITABLE_FIELDS:
        parts.append("the whole farm")
    elif query.intent == QueryIntent.NITROGEN_HISTORY:
        parts.append("every logged season")
    parts.append(TOPIC_LABELS.get(query.intent, query.intent.value.replace("_", " ")))
    return " · ".join(parts)


def _bad_field(f: str) -> str:
    return f"Was {f} a bad field or just a bad year?"


def _yield_check(f: str, s: int) -> str:
    return f"Do the yield monitor and scale tickets agree on {f} in {s}?"


def _seed_cost(f: str, s: int) -> str:
    return f"Does the seed cost on {f} in {s} look right?"


def _zones(f: str, s: int) -> str:
    return f"Is any part of {f} losing money in {s}?"


def _weather(s: int) -> str:
    return f"How dry was {s}?"


def _soil(f: str) -> str:
    return f"How much water does {f}'s soil hold?"


def _applied(f: str, s: int) -> str:
    return f"What did I put on {f} in {s}?"


def _nitrogen(f: str) -> str:
    return f"Did I put the same nitrogen on {f} every year?"


_LAST_FIVE = "Which fields made money in the last five years?"


def suggest_followups(result: AnswerResult) -> list[str]:
    """Up to three next questions, each fully spelled out. Empty for a refusal."""
    query = result.query
    if not result.ok or query is None:
        return []
    payload = result.payload or {}
    field = _record_field_name(result) or query.field_name
    season = query.season
    latest = SEASONS[-1]
    out: list[str] = []
    intent = query.intent

    if intent in (QueryIntent.BAD_FIELD_OR_BAD_YEAR, QueryIntent.EXPLAIN_SHORTFALL) and field:
        evidence = payload.get("evidence") or {}
        outliers = evidence.get("outlier_seasons") or []
        if intent == QueryIntent.BAD_FIELD_OR_BAD_YEAR and payload.get("verdict") == "bad_year":
            out.append(f"Why was {field} a bad year?")
        if intent == QueryIntent.EXPLAIN_SHORTFALL:
            out.append(_bad_field(field))
            if outliers:
                out.append(_weather(outliers[0]))
        if outliers:
            out.append(_yield_check(field, outliers[0]))
        out.append(_zones(field, latest))
        out.append(_LAST_FIVE)
    elif intent == QueryIntent.WHICH_FIELDS_MADE_MONEY:
        rows = [r for r in payload.get("results") or [] if isinstance(r, dict)]
        names = [r.get("display_name") for r in rows if isinstance(r.get("display_name"), str)]
        if names:
            out.append(_bad_field(names[-1]))
            out.append(_bad_field(names[0]))
        if sorted(query.seasons or []) == SEASONS[-5:]:
            out.append(f"Which fields made money in {latest}?")
        else:
            out.append(_LAST_FIVE)
    elif intent == QueryIntent.ZONE_PROFITABILITY and field and season:
        out.append(_seed_cost(field, season))
        if season - 1 in _AS_APPLIED_SEASONS:
            out.append(_zones(field, season - 1))
        out.append(_bad_field(field))
    elif intent == QueryIntent.YIELD_RECONCILIATION and field and season:
        if season - 1 in SEASONS:
            out.append(_yield_check(field, season - 1))
        if season in _AS_APPLIED_SEASONS:
            out.append(_seed_cost(field, season))
        out.append(_bad_field(field))
    elif intent == QueryIntent.COST_RECONCILIATION and field and season:
        if season - 1 in _AS_APPLIED_SEASONS:
            out.append(_seed_cost(field, season - 1))
        out.append(_zones(field, season))
        out.append(_yield_check(field, season))
    elif intent == QueryIntent.RESOLVE_FIELD_NAME and field and season:
        out.append(_bad_field(field))
        out.append(_yield_check(field, season))
    elif intent == QueryIntent.UNPROFITABLE_ZONES_IN_PROFITABLE_FIELDS:
        out.append(_LAST_FIVE)
    elif intent == QueryIntent.SEASON_WEATHER and season:
        if season - 1 in SEASONS:
            out.append(_weather(season - 1))
        out.append(f"Which fields made money in {season}?")
    elif intent == QueryIntent.FIELD_SOIL and field:
        out.append(_nitrogen(field))
        out.append(_bad_field(field))
    elif intent == QueryIntent.APPLIED_INPUTS and field and season:
        if payload.get("logged"):
            out.append(_seed_cost(field, season))
        out.append(_nitrogen(field))
        out.append(_weather(season))
    elif intent == QueryIntent.NITROGEN_HISTORY and field:
        rows = [r for r in payload.get("nitrogen_by_season") or [] if isinstance(r, dict)]
        if rows:
            out.append(_applied(field, rows[-1].get("season", latest)))
        out.append(_soil(field))
        out.append(_bad_field(field))

    seen: set[str] = set()
    unique = [q for q in out if not (q in seen or seen.add(q))]
    return unique[:MAX_SUGGESTIONS]
