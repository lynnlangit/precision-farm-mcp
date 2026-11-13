"""The 15 evaluation questions from docs/EVAL_QUESTIONS.md, asked in plain
English through the real path: Gemma parses the question, the host routes it
to an MCP tool, and the narrator answers. test_eval_questions.py calls the
tools directly, so it can't catch a parser misroute (eval 9 once went
out_of_scope) or a wrong summary line (eval 3 once said "no loss pattern").

Opt-in and slow (one model round-trip or two per question). Needs Ollama
running with gemma3:4b; skipped otherwise. Run with:

    uv run --project host pytest -m eval_nl host/tests

For each question this checks, from the audit log: (i) the parsed intent and
the server/tool it routed to, (ii) the tool's arguments (field, season or
seasons), and (iii) the answer -- its verified lead figures, its Therefore
line, or its refusal code.
"""

from __future__ import annotations

import dataclasses

import pytest

from farm_core.audit import AuditLog
from farm_host.cli import answer_question
from farm_host.preflight_cli import REQUIRED_MODEL, check_model_pulled, check_ollama_running

pytestmark = pytest.mark.eval_nl


def _ollama_ready() -> tuple[bool, str]:
    running, pulled = check_ollama_running()
    if not running.ok:
        return False, running.detail
    model = check_model_pulled(pulled)
    return model.ok, model.detail


_READY, _WHY = _ollama_ready()
if not _READY:
    pytestmark = [pytest.mark.eval_nl, pytest.mark.skip(reason=f"needs Ollama + {REQUIRED_MODEL}: {_WHY}")]


@dataclasses.dataclass(frozen=True)
class Eval:
    number: int
    question: str
    intent: str
    server: str
    tool: str
    args: dict
    contains: tuple[str, ...] = ()  # verified figures that must appear in the answer
    therefore: str | None = None  # expected Therefore line (substring); None = no line
    refusal_code: str | None = None  # expected structured refusal instead of an answer


EVALS = [
    Eval(1, "Was the Marginal Eighty a bad field or just a bad year?",
         "bad_field_or_bad_year", "report-export", "bad_field_or_bad_year",
         {"field_name": "Marginal Eighty"},
         contains=("bad field, not a bad year", "10 of its 10"),
         therefore="lost money in 100% of its 10 recorded seasons"),
    Eval(2, "Was East 80 a bad field or just a bad year?",
         "bad_field_or_bad_year", "report-export", "bad_field_or_bad_year",
         {"field_name": "East 80"},
         contains=("bad year, not a bad field", "2020", "$68.19/ac"),
         therefore="the loss was isolated to 2020"),
    Eval(3, "Was South 160 South a bad field or just a bad year?",
         "bad_field_or_bad_year", "report-export", "bad_field_or_bad_year",
         {"field_name": "South 160 South"},
         contains=("1 of 6 recorded seasons", "$175.41/ac"),
         therefore="lost money in 1 of 6 recorded seasons"),
    Eval(4, "Which fields made money in the last five years?",
         "which_fields_made_money", "report-export", "which_fields_made_money",
         {"seasons": [2021, 2022, 2023, 2024, 2025]},
         contains=("East 80 ($135,533.57)",),
         therefore="12 of 13 fields made money over 2021-2025; East 80 ranked highest "
         "($135,533.57), Marginal Eighty lowest (-$112,044.65)"),
    Eval(5, "Which fields made money in 2019 and 2020?",
         "which_fields_made_money", "report-export", "which_fields_made_money",
         {"seasons": [2019, 2020]},
         contains=("Depot Forty ($17,551.40)",),
         therefore="3 of 14 fields made money over 2019-2020; Depot Forty ranked highest "
         "($17,551.40)"),
    Eval(6, 'What does "north eighty" refer to in 2017?',
         "resolve_field_name", "field-registry", "resolve_field_name",
         {"raw_name": "north eighty", "season": 2017},
         contains=("N 80",)),
    Eval(7, "Do the yield monitor and scale tickets agree on Home Quarter in 2019?",
         "yield_reconciliation", "yield-history", "get_yield_reconciliation",
         {"field_name": "Home Quarter", "season": 2019},
         contains=("5,008.2 bu", "4,683.5 bu", "do not agree")),
    Eval(8, "Is there anything odd about the yield monitor coverage on Marginal Eighty in 2024?",
         "yield_reconciliation", "yield-history", "get_yield_reconciliation",
         {"field_name": "Marginal Eighty", "season": 2024},
         contains=("17,513.6 bu", "17,430.5 bu", "agree within tolerance", "coverage has a gap")),
    Eval(9, "Does the seed cost on Riverside in 2022 look right?",
         "cost_reconciliation", "cost-ledger", "get_cost_reconciliation",
         {"field_name": "Riverside", "season": 2022},
         contains=("doesn't look right", "$95.55/ac", "$60.04/ac")),
    Eval(10, 'What does "Township Rd 12" refer to in 2020?',
         "resolve_field_name", "field-registry", "resolve_field_name",
         {"raw_name": "Township Rd 12", "season": 2020},
         refusal_code="not_found"),
    Eval(11, "Is any part of Section Corner losing money in 2024, even though the field "
         "overall is profitable?",
         "zone_profitability", "report-export", "zone_profitability",
         {"field_name": "Section Corner", "season": 2024},
         contains=("$5,897.56", "zone 0 (-$11,943.49)"),
         therefore="1 of 4 measurable zones lost money"),
    Eval(12, "How dry was 2018?",
         "season_weather", "weather-history", "get_season_weather",
         {"season": 2018},
         contains=("172.6 mm", "60% below the 10-season farm average of 434.4 mm",
                   "driest of the 10 seasons", "277.4 mm short of the 450 mm")),
    Eval(13, "How much water does Coulee Field's soil hold?",
         "field_soil", "weather-history", "get_field_soil",
         {"field_name": "Coulee Field"},
         contains=("6.93 inches", "4.08 in (West 120)")),
    Eval(14, "What did I put on Coulee Field in 2023?",
         "applied_inputs", "as-applied", "get_applied_inputs",
         {"field_name": "Coulee Field", "season": 2023},
         contains=("nitrogen at 145.9 lb N/ac", "logged as 41.22 gal/ac of UAN 32%")),
    Eval(15, "Did I put the same nitrogen on Section Corner every year?",
         "nitrogen_history", "as-applied", "get_nitrogen_history",
         {"field_name": "Section Corner"},
         contains=("2023 corn 160.6", "from 141.3 (2025) to 160.6 (2023)",
                   "no as-applied log before 2022")),
]


def _norm(value):
    return value.strip().lower() if isinstance(value, str) else value


@pytest.mark.parametrize("ev", EVALS, ids=lambda e: f"eval{e.number}")
async def test_eval_question_end_to_end(ev: Eval, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    audit_log = AuditLog(audit_path)
    result = await answer_question(
        ev.question, audit_log, env_overrides={"FARM_AUDIT_LOG": str(audit_path)}
    )
    events = AuditLog(audit_path).entries()
    by_event = {e["event"]: e for e in events}

    # (i) parsed intent and routing
    assert "parse_refused" not in by_event, by_event.get("parse_refused")
    assert by_event["parsed"]["intent"] == ev.intent
    call = by_event["tool_call"]
    assert (call["server"], call["tool"]) == (ev.server, ev.tool)

    # (ii) tool arguments (field names compared case-insensitively)
    for key, expected in ev.args.items():
        assert _norm(call["args"].get(key)) == _norm(expected), (key, call["args"])

    # (iii) refusal code, or the verified answer and its Therefore line
    if ev.refusal_code:
        assert not result.ok
        assert by_event["tool_refused"]["code"] == ev.refusal_code
        return
    assert result.ok, result.text
    for figure in ev.contains:
        assert figure in result.text, (figure, result.text)
    if ev.therefore:
        assert "Therefore: " in result.text and ev.therefore in result.text, result.text
    else:
        assert "Therefore:" not in result.text, result.text
    # The server side of the call landed in the same audit file (P5 --audit-log fix).
    assert "tool_executed" in by_event
    assert AuditLog(audit_path).verify() is True


# --- Multi-turn evals: follow-up questions (grower web app) ---------------
#
# Each follow-up carries only the last verified answer's field, season and
# question type (farm_host.followups.next_context), exactly as the web app
# does. These check that the follow-up resolves to the right lookup, and that
# it is then verified like any first question (its own tool call and
# narration, with the expected verified figures) -- a follow-up can't skip
# the checks or reuse an earlier answer.


@dataclasses.dataclass(frozen=True)
class FollowUpEval:
    name: str
    first: str
    follow_up: str
    intent: str
    args: dict
    contains: tuple[str, ...] = ()
    refused_kind: str | None = None  # expected parse refusal instead of an answer


FOLLOW_UP_EVALS = [
    # Swap the field, keep the question type.
    FollowUpEval("swap_field", "Was East 80 a bad field or just a bad year?",
                 "What about Marginal Eighty?",
                 "bad_field_or_bad_year", {"field_name": "Marginal Eighty"},
                 contains=("bad field, not a bad year", "10 of its 10")),
    # Swap the year, keep the field and question type.
    FollowUpEval("swap_year", "Does the seed cost on Riverside in 2022 look right?",
                 "And in 2023?",
                 "cost_reconciliation", {"field_name": "Riverside", "season": 2023},
                 contains=("Riverside in 2023 is in line with its as-applied records",)),
    # Swap the field, keep the season and question type.
    FollowUpEval("swap_field_keep_season",
                 "Do the yield monitor and scale tickets agree on Home Quarter in 2019?",
                 "What about East 80?",
                 "yield_reconciliation", {"field_name": "East 80", "season": 2019},
                 contains=("23,593.3 bu", "23,532.2 bu", "agree within tolerance")),
    # Swap the year on a weather question.
    FollowUpEval("weather_swap_year", "How dry was 2018?", "And 2019?",
                 "season_weather", {"season": 2019},
                 contains=("2019 had 308.6 mm of rain",)),
    # Keep the field, change the question type to a new server.
    FollowUpEval("applied_then_nitrogen", "What did I put on Coulee Field in 2023?",
                 "Was the nitrogen the same every year?",
                 "nitrogen_history", {"field_name": "Coulee Field"},
                 contains=("from 145.9 (2023) to 179.1 (2022)",)),
    # Context never turns an out-of-scope question into a lookup.
    FollowUpEval("still_out_of_scope", "Was East 80 a bad field or just a bad year?",
                 "What should I plant there next year?",
                 "", {}, refused_kind="out_of_scope"),
]


@pytest.mark.parametrize("ev", FOLLOW_UP_EVALS, ids=lambda e: e.name)
async def test_follow_up_end_to_end(ev: FollowUpEval, tmp_path):
    from farm_host.followups import next_context

    env = {"FARM_AUDIT_LOG": str(tmp_path / "first.jsonl")}
    first = await answer_question(ev.first, AuditLog(tmp_path / "first.jsonl"), env_overrides=env)
    assert first.ok, first.text
    context = next_context(first, None)

    audit_path = tmp_path / "follow_up.jsonl"
    result = await answer_question(
        ev.follow_up,
        AuditLog(audit_path),
        env_overrides={"FARM_AUDIT_LOG": str(audit_path)},
        context=context,
    )
    by_event = {e["event"]: e for e in AuditLog(audit_path).entries()}
    assert by_event["query"]["follow_up_context"]["field_name"] == context.field_name

    if ev.refused_kind:
        assert not result.ok
        assert by_event["parse_refused"]["kind"] == ev.refused_kind
        assert "tool_call" not in by_event
        return

    assert "parse_refused" not in by_event, by_event.get("parse_refused")
    assert by_event["parsed"]["intent"] == ev.intent
    for key, expected in ev.args.items():
        assert _norm(by_event["tool_call"]["args"].get(key)) == _norm(expected), by_event
    # Verified from scratch: its own lookup, its own narration and checks.
    assert "tool_executed" in by_event and "narration" in by_event
    assert result.ok, result.text
    for figure in ev.contains:
        assert figure in result.text, (figure, result.text)
    assert AuditLog(audit_path).verify() is True
