"""Phase 5 verification: Gemma is bounded to exactly two jobs, enforced
structurally (this module never imports a database, an MCP client, or any
tool), and every claim it narrates is traceable to the payload it was given.
Runs against a real local Ollama + gemma3:4b -- no mocking, since the point
is to prove the actual model behaves within these bounds, not that the
scaffolding around a fake one does.
"""

import ast
from pathlib import Path

import pytest

from farm_core import confirm
from farm_core.pipeline import build_farm_snapshot
from farm_core.profitability import bad_field_or_bad_year, which_fields_made_money
from farm_model.narrator import narrate, narrate_verified
from farm_model.query_parser import ParseFailure, parse_question
from farm_model.query_schema import QueryIntent
from farm_model.verification import check_narration_grounded, check_verdict_not_contradicted

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
MODEL_SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "farm_model"


@pytest.fixture(scope="session")
def snapshot():
    # auto_approve here is deliberate and test-only: this suite verifies the
    # model layer's bounds (structural isolation, grounding, narration), not
    # confirmation gating -- that's core/tests/test_confirmation_gate.py.
    return build_farm_snapshot(DATA_DIR, confirm_fn=confirm.auto_approve)


@pytest.fixture(scope="session")
def known_seasons(snapshot):
    return snapshot.seasons


# --- Structural enforcement: the model layer cannot reach a tool or a database ---


def test_farm_model_never_imports_a_database_or_tool_client():
    """No instruction can be bypassed if the capability doesn't exist. This
    walks every module's import statements looking for anything that could
    read raw data or call a tool.
    """
    forbidden_roots = {"duckdb", "farm_core.db", "farm_host", "farm_core.pipeline"}
    for path in MODEL_SRC_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module} if node.module else set()
            else:
                continue
            hit = names & forbidden_roots
            assert not hit, f"{path.name} imports forbidden module(s): {hit}"


# --- Job 1: parsing stays inside the fixed menu, never guesses ---


def test_parses_bad_field_or_bad_year_with_drifted_field_name(known_seasons):
    result = parse_question("Was the north eighty a bad field or just a bad year?", known_seasons)
    assert result.intent == QueryIntent.BAD_FIELD_OR_BAD_YEAR
    assert result.field_name is not None and "north eighty" in result.field_name.lower()


def test_relative_season_window_resolved_deterministically_not_by_model(known_seasons):
    result = parse_question("Which fields made money in the last five years?", known_seasons)
    assert result.intent == QueryIntent.WHICH_FIELDS_MADE_MONEY
    # Must be exactly the 5 most recent known seasons -- computed in Python
    # against known_seasons, not whatever five years the model might guess.
    assert result.seasons == sorted(known_seasons)[-5:]


def test_explicit_years_are_not_reinterpreted_as_a_relative_count(known_seasons):
    result = parse_question("Which fields made money in 2019 and 2020?", known_seasons)
    assert result.intent == QueryIntent.WHICH_FIELDS_MADE_MONEY
    assert result.seasons == [2019, 2020]


def test_out_of_scope_question_is_refused_not_forced(known_seasons):
    result = parse_question(
        "What should I plant next year on the north eighty?", known_seasons
    )
    assert isinstance(result, ParseFailure)


def test_underspecified_question_is_refused_not_guessed(known_seasons):
    """No timeframe stated at all -- correct behavior is to ask, not to
    silently assume "all seasons" or any other default.
    """
    result = parse_question("Which fields made money overall?", known_seasons)
    assert isinstance(result, ParseFailure)


# --- Job 2: narration is grounded in the payload it was given, nothing more ---


def test_narration_grounded_for_bad_field_verdict(snapshot):
    canonical_id = snapshot.canonical_id_for_name("Marginal Eighty")
    payload = bad_field_or_bad_year(snapshot.profit_records, canonical_id)
    question = "Was the Marginal Eighty a bad field or a bad year?"

    narration = narrate(question, payload)
    result = check_narration_grounded(narration, payload, question=question)
    assert result.is_grounded, f"ungrounded numbers {result.ungrounded_numbers} in: {narration}"
    assert "bad" in narration.lower() or "loss" in narration.lower()


def test_narration_grounded_for_catastrophic_year_verdict(snapshot):
    canonical_id = snapshot.canonical_id_for_name("East 80")
    payload = bad_field_or_bad_year(snapshot.profit_records, canonical_id)
    assert payload["verdict"] == "bad_year"
    question = "Was East 80 a bad field or just a bad year?"

    narration = narrate(question, payload)
    result = check_narration_grounded(narration, payload, question=question)
    assert result.is_grounded, f"ungrounded numbers {result.ungrounded_numbers} in: {narration}"


def test_narration_grounded_for_which_fields_made_money(snapshot, known_seasons):
    seasons = sorted(known_seasons)[-5:]
    results = which_fields_made_money(snapshot.profit_records, seasons)
    payload = {"results": results[:5]}  # top 5, keep the payload narration-sized
    question = "Which fields made money in the last five years?"

    narration = narrate(question, payload)
    result = check_narration_grounded(narration, payload, question=question)
    assert result.is_grounded, f"ungrounded numbers {result.ungrounded_numbers} in: {narration}"


def test_grounding_check_actually_detects_fabricated_numbers():
    """Regression guard on the detector itself: it must not be a rubber
    stamp that always passes.
    """
    payload = {"total_profit": 169720.44, "display_name": "Section Corner"}
    fabricated = "Section Corner made an incredible $999,999.99 in profit."
    result = check_narration_grounded(fabricated, payload)
    assert not result.is_grounded
    assert 999999.99 in result.ungrounded_numbers


# --- Semantic guard: numeric grounding alone can't catch a contradicted verdict ---


def test_verdict_contradiction_check_catches_the_observed_failure_mode():
    """Regression test for a real failure seen from gemma3:4b: given a
    loss_rate=1.0 bad_field payload, it narrated "...it appears the issue
    was likely due to a bad year rather than a specific field problem" --
    every number in that sentence was grounded (there were none), so
    check_narration_grounded alone passed it. This is exactly what
    check_verdict_not_contradicted exists to catch.
    """
    payload = {
        "verdict": "bad_field",
        "evidence": {"loss_rate": 1.0, "num_seasons": 10},
    }
    observed_bad_narration = (
        "This indicates that the field has consistently performed poorly across "
        "multiple years. Therefore, it appears the issue was likely due to a bad "
        "year rather than a specific field problem."
    )
    assert not check_verdict_not_contradicted(observed_bad_narration, payload)

    good_narration = "This field lost money in every one of the 10 recorded seasons."
    assert check_verdict_not_contradicted(good_narration, payload)


def test_narrate_verified_never_returns_a_contradicted_verdict(snapshot):
    """narrate_verified must not let a verdict-contradicting narration reach
    the farmer -- either the model gets it right (possibly after a retry) or
    the deterministic fallback kicks in. Either way, the result must never
    contradict the payload.
    """
    canonical_id = snapshot.canonical_id_for_name("Marginal Eighty")
    payload = bad_field_or_bad_year(snapshot.profit_records, canonical_id)
    payload["field_name"] = "Marginal Eighty"
    assert payload["verdict"] == "bad_field"

    question = "Was the Marginal Eighty a bad field or a bad year?"
    narration = narrate_verified(question, payload)
    assert check_verdict_not_contradicted(narration, payload), narration
    grounding = check_narration_grounded(narration, payload, question=question)
    assert grounding.is_grounded, f"ungrounded numbers {grounding.ungrounded_numbers}"
