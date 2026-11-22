"""farm-evals without a model: the answer key's grade() and the comparison
report, fed hand-built answers and audit entries. The real runs (which ask
Ollama) are farm-evals itself; see docs/MODELS.md."""

from __future__ import annotations

from farm_host.cli import AnswerResult
from farm_host.eval_key import EVALS, FARM1_EVALS, grade
from farm_host.evals_cli import Run, _with_tag, report

EV2 = next(e for e in EVALS if e.number == 2)
EV10 = next(e for e in EVALS if e.number == 10)


def _events(ev, args=None, tool=None, refused=None):
    events = [
        {"event": "parsed", "intent": ev.intent},
        {"event": "tool_call", "server": ev.server, "tool": tool or ev.tool, "args": args or ev.args},
    ]
    if refused:
        events.append({"event": "tool_refused", "code": refused})
    return events


GOOD_TEXT = (
    "East 80 was a bad year, not a bad field: it lost $68.19/ac in 2020.\n"
    "Therefore: the loss was isolated to 2020."
)


def test_answer_key_has_15_plus_4_questions():
    assert len(EVALS) == 15
    assert len(FARM1_EVALS) == 4
    assert len({e.id for e in EVALS + FARM1_EVALS}) == 19


def test_grade_passes_a_matching_answer():
    g = grade(EV2, AnswerResult(text=GOOD_TEXT, ok=True), _events(EV2))
    assert g.passed, g.problems()


def test_grade_names_a_misroute_and_stops_there():
    g = grade(EV2, AnswerResult(text="", ok=True), _events(EV2, tool="zone_profitability"))
    assert g.route and not g.args and not g.answer


def test_grade_names_a_wrong_field():
    g = grade(EV2, AnswerResult(text=GOOD_TEXT, ok=True), _events(EV2, args={"field_name": "West 120"}))
    assert g.args and not g.route


def test_grade_names_a_missing_figure():
    g = grade(EV2, AnswerResult(text=GOOD_TEXT.replace("$68.19/ac", "$70/ac"), ok=True), _events(EV2))
    assert any("$68.19/ac" in p for p in g.answer)


def test_grade_checks_the_refusal_code():
    ok = grade(EV10, AnswerResult(text="", ok=False), _events(EV10, refused="not_found"))
    assert ok.passed
    wrong = grade(EV10, AnswerResult(text="", ok=False), _events(EV10, refused="ambiguous"))
    assert wrong.answer


def test_grade_reports_a_parse_refusal():
    g = grade(EV2, AnswerResult(text="", ok=False), [{"event": "parse_refused", "kind": "invalid_output"}])
    assert g.route


def test_report_puts_models_side_by_side():
    a = Run("gemma3:4b", EV2, grade(EV2, AnswerResult(text=GOOD_TEXT, ok=True), _events(EV2)),
            "withheld", 2.0, GOOD_TEXT)
    b = Run("phi4-mini:latest", EV2,
            grade(EV2, AnswerResult(text="", ok=True), _events(EV2, tool="zone_profitability")),
            "none", 4.0, "")
    text = report(["gemma3:4b", "phi4-mini:latest", "other:1b"], [a, b], {"other:1b": "not pulled"})
    assert "| `gemma3:4b` | 1 of 1 | 0 | 0 | 0 | 0 | 1 | 2.0 |" in text
    assert "| `phi4-mini:latest` | 0 of 1 | 1 |" in text
    assert "| eval2 | Was East 80 a bad field or just a bad year? | pass | **FAIL** (route) |" in text
    assert "`other:1b` | skipped: not pulled" in text
    assert "`phi4-mini:latest` eval2: routed to" in text


def test_with_tag_matches_ollama_list_names():
    assert _with_tag("phi4-mini", ["phi4-mini:latest"]) == "phi4-mini:latest"
    assert _with_tag("gemma3:4b", ["gemma3:4b"]) == "gemma3:4b"
    assert _with_tag("phi4-mini", None) == "phi4-mini"


def test_cli_accepts_model_flag():
    from farm_host.cli import parse_args

    assert parse_args(["--model", "phi4-mini", "how dry was 2018"]).model == "phi4-mini"
    assert parse_args(["how dry was 2018"]).model is None
