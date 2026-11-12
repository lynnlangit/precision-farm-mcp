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
from farm_model.query_schema import QueryIntent

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
