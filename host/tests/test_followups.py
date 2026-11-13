"""Model-free tests for follow-up questions (farm_host.followups): what a
follow-up carries forward, the "Showing:" label, and the suggested next
questions. No Ollama and no MCP servers. Payloads mirror seed-42 results."""

from __future__ import annotations

from farm_host.cli import AnswerResult
from farm_host.followups import (
    MAX_SUGGESTIONS,
    next_context,
    resolved_label,
    suggest_followups,
)
from farm_model.query_schema import FollowUpContext, QueryIntent, QueryObject

EAST_80 = {
    "verdict": "bad_year",
    "evidence": {"outlier_seasons": [2020], "median_profit_per_acre": 68.19},
    "field_name": "East 80",
}
YIELD_HQ = {"field_name": "Home Quarter", "season": 2019, "totals_discrepancy": True}
COST_RIVERSIDE = {
    "results": [
        {"field_name": "Sheyenne Bottom", "season": 2022, "line_item": "seed"},
        {"field_name": "Sheyenne Bottom", "season": 2022, "line_item": "fertilizer"},
    ]
}


def _ok(intent, payload, **query) -> AnswerResult:
    q = QueryObject(intent=intent, **query)
    args = {k: v for k, v in query.items() if k in ("field_name", "raw_name", "season", "seasons")}
    return AnswerResult(text="x", ok=True, query=q, tool_args=args, payload=payload)


def test_context_comes_from_the_verified_record_name():
    # The farmer typed lower case; the record spelling is what's carried.
    r = _ok(QueryIntent.YIELD_RECONCILIATION, YIELD_HQ, field_name="home quarter", season=2019)
    ctx = next_context(r, None)
    assert ctx == FollowUpContext(
        field_name="Home Quarter", season=2019, intent=QueryIntent.YIELD_RECONCILIATION
    )


def test_resolved_alias_is_carried_as_the_canonical_name():
    r = _ok(
        QueryIntent.RESOLVE_FIELD_NAME,
        {"canonical_boundary_name": "N 80", "method": "alias"},
        raw_name="north eighty",
        season=2017,
    )
    assert next_context(r, None).field_name == "N 80"


def test_a_refusal_never_moves_the_context():
    before = FollowUpContext(
        field_name="East 80", season=2020, intent=QueryIntent.ZONE_PROFITABILITY
    )
    refused = AnswerResult(text="no", ok=False, refusal_kind="unparseable")
    assert next_context(refused, before) is before
    tool_refused = AnswerResult(
        text="no",
        ok=False,
        query=QueryObject(intent=QueryIntent.ZONE_PROFITABILITY, field_name="X", season=2020),
        refusal_kind="tool_refused",
    )
    assert next_context(tool_refused, before) is before


def test_context_keeps_the_season_when_the_new_question_has_none():
    before = FollowUpContext(field_name="Sheyenne Bottom", season=2022)
    r = _ok(QueryIntent.BAD_FIELD_OR_BAD_YEAR, EAST_80, field_name="East 80")
    ctx = next_context(r, before)
    assert (ctx.field_name, ctx.season, ctx.intent) == (
        "East 80", 2022, QueryIntent.BAD_FIELD_OR_BAD_YEAR
    )


def test_context_never_holds_numbers_from_the_answer():
    r = _ok(QueryIntent.BAD_FIELD_OR_BAD_YEAR, EAST_80, field_name="East 80")
    assert set(next_context(r, None).model_dump()) == {"field_name", "season", "intent"}


def test_resolved_labels():
    assert resolved_label(
        _ok(QueryIntent.YIELD_RECONCILIATION, YIELD_HQ, field_name="Home Quarter", season=2019)
    ) == "Home Quarter · 2019 · yield monitor vs scale tickets"
    assert resolved_label(
        _ok(QueryIntent.WHICH_FIELDS_MADE_MONEY, {"results": []},
            seasons=[2021, 2022, 2023, 2024, 2025])
    ) == "2021–2025 · which fields made money"
    assert resolved_label(
        _ok(QueryIntent.BAD_FIELD_OR_BAD_YEAR, EAST_80, field_name="East 80")
    ) == "East 80 · every season on record · bad field or bad year"
    assert resolved_label(AnswerResult(text="x", ok=False)) is None


def test_suggestions_after_a_bad_year():
    s = suggest_followups(_ok(QueryIntent.BAD_FIELD_OR_BAD_YEAR, EAST_80, field_name="East 80"))
    assert s == [
        "Why was East 80 a bad year?",
        "Do the yield monitor and scale tickets agree on East 80 in 2020?",
        "Is any part of East 80 losing money in 2025?",
    ]


def test_suggestions_after_a_cost_check_compare_years():
    s = suggest_followups(
        _ok(QueryIntent.COST_RECONCILIATION, COST_RIVERSIDE, field_name="Sheyenne Bottom", season=2023)
    )
    assert s[0] == "Does the seed cost on Sheyenne Bottom in 2022 look right?"
    assert "Is any part of Sheyenne Bottom losing money in 2023?" in s


def test_suggestions_never_offer_a_season_without_as_applied_logs():
    # 2022 is the oldest as-applied season, so no "2021" cost suggestion.
    s = suggest_followups(
        _ok(QueryIntent.COST_RECONCILIATION, COST_RIVERSIDE, field_name="Sheyenne Bottom", season=2022)
    )
    assert not any("2021" in q for q in s)


def test_suggestions_after_ranking_name_the_extremes():
    payload = {"results": [{"display_name": "East 80"}, {"display_name": "Marginal Eighty"}]}
    s = suggest_followups(
        _ok(QueryIntent.WHICH_FIELDS_MADE_MONEY, payload, seasons=[2019, 2020])
    )
    assert s == [
        "Was Marginal Eighty a bad field or just a bad year?",
        "Was East 80 a bad field or just a bad year?",
        "Which fields made money in the last five years?",
    ]


def test_every_suggestion_names_its_field_and_season():
    # Fully spelled out, so a suggestion never depends on the carried context.
    for r in (
        _ok(QueryIntent.YIELD_RECONCILIATION, YIELD_HQ, field_name="Home Quarter", season=2019),
        _ok(QueryIntent.COST_RECONCILIATION, COST_RIVERSIDE, field_name="Sheyenne Bottom", season=2023),
        _ok(QueryIntent.ZONE_PROFITABILITY, {"field_name": "Section Corner"},
            field_name="Section Corner", season=2024),
    ):
        s = suggest_followups(r)
        assert 2 <= len(s) <= MAX_SUGGESTIONS
        for q in s:
            assert any(name in q for name in ("Home Quarter", "Sheyenne Bottom", "Section Corner")), q


def test_no_suggestions_after_a_refusal():
    assert suggest_followups(AnswerResult(text="no", ok=False)) == []
