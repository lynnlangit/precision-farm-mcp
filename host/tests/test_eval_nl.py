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

test_withheld_sentence_demo (xfail: it depends on the model's wording) checks
that the demo question's AI sentence is written and then withheld. Just that
one:

    uv run --project host pytest -m eval_nl host/tests -k withheld
"""

from __future__ import annotations

import dataclasses

import pytest

from farm_core.audit import AuditLog
from farm_host.cli import answer_question
from farm_host.eval_key import EVALS, FARM1_EVALS, Eval, _norm, grade
from farm_host.farms import FARMS
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


@pytest.mark.parametrize("ev", EVALS + FARM1_EVALS, ids=lambda e: e.id)
async def test_eval_question_end_to_end(ev: Eval, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    audit_log = AuditLog(audit_path)
    env = {"FARM_AUDIT_LOG": str(audit_path), **FARMS[ev.farm].server_env()}
    result = await answer_question(ev.question, audit_log, env_overrides=env)
    events = AuditLog(audit_path).entries()
    by_event = {e["event"]: e for e in events}

    # (i) parsed intent and routing, (ii) tool arguments, (iii) refusal code,
    # or the verified answer and its Therefore line -- see eval_key.grade.
    g = grade(ev, result, events)
    assert g.passed, (g.problems(), result.text)
    # The server side of the call landed in the same audit file (P5 --audit-log fix).
    assert "tool_executed" in by_event
    assert AuditLog(audit_path).verify() is True


# --- The withheld-sentence demo: written, then withheld --------------------
#
# Records model behaviour, not code behaviour: whether gemma3:4b writes a
# sentence that fails a check depends on the machine and the model build.
# On Lynn's Mac (4 of 4 runs, both farms) it blamed East 80's 2020 loss on
# "an unusual weather pattern" -- no record names a cause (the true cause,
# hail, is in no record) -- so unsupported_cause withheld it. On another Mac
# the same model wrote a sentence with no cause, which passed every check.
# So this is xfail, not a requirement. The checks themselves are tested
# without the model in model/tests/test_withheld_sentence.py. To pick a new
# demo question, use scripts/probe_narration.py; never loosen a check.

WITHHELD_DEMO_QUESTION = "Was East 80 a bad field or just a bad year?"


@pytest.mark.xfail(
    strict=False,
    reason="records gemma3:4b's wording on one machine and model build, not code behaviour",
)
@pytest.mark.parametrize("farm", ["farm1", "farm2"])
async def test_withheld_sentence_demo(farm: str, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    env = {"FARM_AUDIT_LOG": str(audit_path), **FARMS[farm].server_env()}
    result = await answer_question(WITHHELD_DEMO_QUESTION, AuditLog(audit_path), env_overrides=env)
    assert result.ok, result.text
    n = result.narration
    assert n is not None
    print(f"\n{farm}: shown={n.context!r} rejected={n.rejected_texts} failed={n.failed_checks}")
    # A sentence was written and blocked -- not "nothing to add", not shown.
    assert n.rejected_texts, f"nothing was blocked; the AI's sentence was {n.context!r}"
    assert n.context is None, f"a sentence passed every check: {n.context!r}"
    assert result.text.startswith(n.lead)  # the verified answer alone
    assert "unsupported_cause" in n.failed_checks[0], n.failed_checks


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
    FollowUpEval("swap_year", "Does the seed cost on Sheyenne Bottom in 2022 look right?",
                 "And in 2023?",
                 "cost_reconciliation", {"field_name": "Sheyenne Bottom", "season": 2023},
                 contains=("Sheyenne Bottom in 2023 is in line with its as-applied records",)),
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
