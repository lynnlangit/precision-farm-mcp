"""Model-free tests for query_parser's code-level guards and prompt rules
(eval-fix P2). ollama.chat is replaced with a stub that returns a fixed
QueryObject JSON and records the messages it was sent, so these run without
Ollama. Whether the live model actually follows the prompt rule is covered by
the live test at the bottom (skipped when Ollama isn't reachable).
"""

from __future__ import annotations

import json
import types

import pytest

from farm_model import query_parser
from farm_model.query_parser import ParseFailure, parse_question
from farm_model.query_schema import FollowUpContext, QueryIntent

KNOWN_SEASONS = list(range(2016, 2026))


def _stub_chat(monkeypatch, output: dict) -> dict:
    captured: dict = {}

    def fake_chat(model, messages, format, options):  # noqa: A002 -- mirrors ollama.chat
        captured["messages"] = messages
        return types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(output)))

    monkeypatch.setattr(query_parser.ollama, "chat", fake_chat)
    return captured


def test_cost_reconciliation_rule_and_examples_reach_the_model(monkeypatch):
    captured = _stub_chat(
        monkeypatch,
        {"intent": "cost_reconciliation", "field_name": "Riverside", "season": 2022},
    )
    result = parse_question("Does the seed cost on Riverside in 2022 look right?", KNOWN_SEASONS)
    system_prompt = captured["messages"][0]["content"]
    assert "ALWAYS this intent, never bad_field_or_bad_year" in system_prompt
    assert '"Does the seed cost on Riverside in 2022 look right?"' in system_prompt
    assert not isinstance(result, ParseFailure)
    assert result.intent == QueryIntent.COST_RECONCILIATION
    assert result.field_name == "Riverside"
    assert result.season == 2022


@pytest.mark.parametrize("name", ["-5.16", "2020", "+3", " 42 ", ".5"])
def test_numeric_field_name_is_refused_as_out_of_scope(monkeypatch, name):
    _stub_chat(monkeypatch, {"intent": "bad_field_or_bad_year", "field_name": name})
    result = parse_question(f"What is the seasonal effect of {name}?", KNOWN_SEASONS)
    assert isinstance(result, ParseFailure)
    assert result.kind == "out_of_scope"
    assert result.reason == query_parser.NUMERIC_NAME_REASON


def test_numeric_raw_name_is_refused_as_out_of_scope(monkeypatch):
    _stub_chat(
        monkeypatch, {"intent": "resolve_field_name", "raw_name": "-5.16", "season": 2020}
    )
    result = parse_question("What does -5.16 refer to in 2020?", KNOWN_SEASONS)
    assert isinstance(result, ParseFailure)
    assert result.kind == "out_of_scope"


@pytest.mark.parametrize("name", ["East 80", "N 80", "Township Rd 12", "South 160 South"])
def test_names_containing_digits_still_pass(monkeypatch, name):
    _stub_chat(monkeypatch, {"intent": "bad_field_or_bad_year", "field_name": name})
    result = parse_question(f"Was {name} a bad field or just a bad year?", KNOWN_SEASONS)
    assert not isinstance(result, ParseFailure)
    assert result.field_name == name


# --- follow-up questions (grower web app) ---------------------------------

COST_CONTEXT = FollowUpContext(
    field_name="Riverside", season=2022, intent=QueryIntent.COST_RECONCILIATION
)


def test_no_context_means_no_follow_up_prompt(monkeypatch):
    captured = _stub_chat(monkeypatch, {"intent": "bad_field_or_bad_year", "field_name": "East 80"})
    parse_question("Was East 80 a bad field or just a bad year?", KNOWN_SEASONS)
    assert "follows an earlier one" not in captured["messages"][0]["content"]
    assert len(captured["messages"]) == 2  # system + this question: no chat history


def test_context_reaches_the_prompt_but_not_the_history(monkeypatch):
    captured = _stub_chat(
        monkeypatch, {"intent": "cost_reconciliation", "field_name": "Riverside", "season": 2023}
    )
    result = parse_question("And in 2023?", KNOWN_SEASONS, context=COST_CONTEXT)
    system_prompt = captured["messages"][0]["content"]
    assert 'field: "Riverside"' in system_prompt
    assert "season: 2022" in system_prompt
    assert "question type: cost_reconciliation" in system_prompt
    assert [m["role"] for m in captured["messages"]] == ["system", "user"]
    assert captured["messages"][1]["content"] == "And in 2023?"
    assert not isinstance(result, ParseFailure)
    assert (result.field_name, result.season) == ("Riverside", 2023)


def test_follow_up_may_swap_the_field(monkeypatch):
    _stub_chat(
        monkeypatch, {"intent": "cost_reconciliation", "field_name": "East 80", "season": 2022}
    )
    result = parse_question("What about East 80?", KNOWN_SEASONS, context=COST_CONTEXT)
    assert not isinstance(result, ParseFailure)
    assert (result.field_name, result.season) == ("East 80", 2022)


def test_follow_up_field_from_nowhere_is_refused(monkeypatch):
    # "Home Quarter" is in neither the question nor the context: an invention.
    _stub_chat(
        monkeypatch,
        {"intent": "cost_reconciliation", "field_name": "Home Quarter", "season": 2022},
    )
    result = parse_question("What about the fertilizer?", KNOWN_SEASONS, context=COST_CONTEXT)
    assert isinstance(result, ParseFailure)
    assert result.kind == "unresolved_followup"
    assert "Home Quarter" in result.reason


def test_follow_up_season_from_nowhere_is_refused(monkeypatch):
    _stub_chat(
        monkeypatch, {"intent": "cost_reconciliation", "field_name": "Riverside", "season": 2024}
    )
    result = parse_question("What about the year before?", KNOWN_SEASONS, context=COST_CONTEXT)
    assert isinstance(result, ParseFailure)
    assert result.kind == "unresolved_followup"


def test_follow_up_that_drops_the_named_year_is_refused(monkeypatch):
    # The farmer said 2023 but the model kept the earlier 2022.
    _stub_chat(
        monkeypatch, {"intent": "cost_reconciliation", "field_name": "Riverside", "season": 2022}
    )
    result = parse_question("And in 2023?", KNOWN_SEASONS, context=COST_CONTEXT)
    assert isinstance(result, ParseFailure)
    assert result.kind == "unresolved_followup"
    assert "2023" in result.reason


def test_follow_up_relative_window_still_resolves_in_code(monkeypatch):
    _stub_chat(
        monkeypatch, {"intent": "which_fields_made_money", "season_count_from_latest": 3}
    )
    result = parse_question(
        "Which fields made money in the last three years?", KNOWN_SEASONS, context=COST_CONTEXT
    )
    assert not isinstance(result, ParseFailure)
    assert result.seasons == [2023, 2024, 2025]


def test_follow_up_still_hits_the_existing_guards(monkeypatch):
    _stub_chat(monkeypatch, {"intent": "unrecognized"})
    result = parse_question(
        "What should I plant there next year?", KNOWN_SEASONS, context=COST_CONTEXT
    )
    assert isinstance(result, ParseFailure)
    assert result.kind == "out_of_scope"


def _ollama_ready() -> bool:
    try:
        query_parser.ollama.show(query_parser.DEFAULT_MODEL)
        return True
    except Exception:  # noqa: BLE001 -- any failure means "not available here"
        return False


@pytest.mark.skipif(not _ollama_ready(), reason="needs a local Ollama with the default model")
def test_live_eval_9_parses_as_cost_reconciliation():
    result = parse_question("Does the seed cost on Riverside in 2022 look right?", KNOWN_SEASONS)
    assert not isinstance(result, ParseFailure)
    assert result.intent == QueryIntent.COST_RECONCILIATION
    assert result.field_name == "Riverside"
    assert result.season == 2022


@pytest.mark.skipif(not _ollama_ready(), reason="needs a local Ollama with the default model")
def test_live_numeric_follow_up_is_refused():
    result = parse_question("What is the seasonal effect of -5.16?", KNOWN_SEASONS)
    assert isinstance(result, ParseFailure)
    assert result.kind == "out_of_scope"
