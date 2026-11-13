"""The app builds and binds safely by default (no model, no servers)."""

import farm_web.app as web_app
from farm_host.cli import AnswerResult
from farm_model.query_schema import QueryIntent, QueryObject
from farm_web.app import EXAMPLES, build_app, make_ask, parse_args


def test_app_builds(tmp_path):
    app = build_app(tmp_path / "audit.jsonl")
    assert app.title == "Precision Farm"


def test_localhost_only_by_default():
    assert parse_args([]).lan is False
    assert parse_args(["--lan"]).lan is True


def test_examples_are_the_eval_questions():
    assert sum(len(qs) for _, qs in EXAMPLES) == 10  # eval 10 is a refusal, left out


def _fake_answer(seen: list):
    async def fake(question, audit_log, env_overrides=None, context=None, fleet=None):
        seen.append(context)
        if question == "nonsense":
            return AnswerResult(text="no", ok=False, refusal_kind="unparseable")
        return AnswerResult(
            text="East 80 had a bad year.",
            ok=True,
            query=QueryObject(intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR, field_name="east 80"),
            tool_args={"field_name": "east 80"},
            payload={"verdict": "bad_year", "field_name": "East 80",
                     "evidence": {"outlier_seasons": [2020]}},
        )
    return fake


class _FakePool:
    """Stands in for ServerPool: no servers, the coroutine just runs."""

    def run(self, fn):
        import asyncio

        return asyncio.run(fn(None))


def test_ask_carries_context_and_offers_follow_ups(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.setattr(web_app, "answer_question", _fake_answer(seen))
    ask = make_ask(tmp_path / "audit.jsonl", _FakePool())

    out = ask("Was east 80 a bad field or just a bad year?", None)
    answer_html, _, _, _, state, hint, heading, *buttons = out
    assert seen == [None]  # a first question has no context
    assert state == {"field_name": "East 80", "season": None, "intent": "bad_field_or_bad_year"}
    assert "East 80" in hint and "Showing:" in answer_html
    assert heading["visible"] is True
    assert buttons[0]["value"] == "Why was East 80 a bad year?"
    assert all(b["visible"] for b in buttons)

    # The next question gets that context; a refusal keeps it and hides suggestions.
    out = ask("nonsense", state)
    assert seen[-1].field_name == "East 80"
    assert out[4] == state
    assert out[6]["visible"] is False and not any(b["visible"] for b in out[7:])


def _check(name, ok):
    from farm_host.preflight_cli import CheckResult

    return CheckResult(name=name, ok=ok, detail="d", fix=None if ok else "do the thing")


def test_ready_check_collapses_when_all_pass_and_opens_on_a_problem(monkeypatch):
    monkeypatch.setattr(web_app, "check_ollama_running", lambda: (_check("Ollama", True), []))
    monkeypatch.setattr(web_app, "check_model_pulled", lambda pulled: _check("gemma", True))
    monkeypatch.setattr(web_app, "check_synthetic_data", lambda d: _check("data", True))
    monkeypatch.setattr(web_app, "check_confirmed_mappings", lambda d: _check("ingest", True))
    html = web_app.status_html()
    assert html.startswith('<details class="pf-status-wrap">')  # collapsed
    assert "Prerequisites loaded" in html and "4 of 4" in html
    assert web_app.status_panels() == ("", html)  # at the bottom

    monkeypatch.setattr(web_app, "check_model_pulled", lambda pulled: _check("gemma", False))
    html = web_app.status_html()
    assert html.startswith('<details class="pf-status-wrap" open>')
    assert "1 of 4 need attention" in html and "do the thing" in html
    assert web_app.status_panels() == (html, "")  # at the top


def test_example_groups_start_collapsed(tmp_path):
    app = build_app(tmp_path / "audit.jsonl", _FakePool())
    accordions = [b for b in app.blocks.values() if type(b).__name__ == "Accordion"]
    assert len(accordions) == len(EXAMPLES)
    assert all(a.open is False for a in accordions)
    assert accordions[0].label == "Bad field or bad year? (3)"
