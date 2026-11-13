"""The 11 evaluation questions from docs/EVAL_QUESTIONS.md, asked in plain
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
