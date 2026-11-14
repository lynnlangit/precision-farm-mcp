"""The app builds and binds safely by default (no model, no servers)."""

import farm_web.app as web_app
from farm_host.cli import AnswerResult
from farm_model.query_schema import QueryIntent, QueryObject
from farm_host.farms import FARMS
from farm_web.app import EXAMPLES, FarmPools, build_app, make_ask, parse_args


def test_app_builds(tmp_path):
    app = build_app(tmp_path / "audit.jsonl")
    assert app.title == "Precision Farm"


def test_localhost_only_by_default():
    assert parse_args([]).lan is False
    assert parse_args(["--lan"]).lan is True


def test_examples_are_the_eval_questions():
    assert sum(len(qs) for _, qs in EXAMPLES) == 15  # eval 10 is a refusal, left out
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[2] / "docs" / "EVAL_QUESTIONS.md").read_text()
    for _, qs in EXAMPLES:
        for q in qs:
            assert f"**Q:** {q}" in doc, q


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

    def __init__(self, farm=None):
        self.farm = farm

    def run(self, fn):
        import asyncio

        return asyncio.run(fn(None))


def _fake_pools(tmp_path, made=None):
    def factory(farm):
        if made is not None:
            made.append(farm.key)
        return _FakePool(farm)

    return FarmPools(tmp_path / "audit.jsonl", factory=factory)


def test_ask_carries_context_and_offers_follow_ups(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.setattr(web_app, "answer_question", _fake_answer(seen))
    ask = make_ask(tmp_path / "audit.jsonl", _fake_pools(tmp_path))

    out = ask("Was east 80 a bad field or just a bad year?", None)
    answer_html, _, _, _, state, heading, *buttons = out
    assert seen == [None]  # a first question has no context
    assert state == {"field_name": "East 80", "season": None, "intent": "bad_field_or_bad_year"}
    # What a follow-up builds on is shown once, in the answer card's Showing line.
    assert "Showing:" in answer_html and "East 80" in answer_html
    assert heading["visible"] is True
    assert buttons[0]["value"] == "Why was East 80 a bad year?"
    assert all(b["visible"] for b in buttons)

    # The next question gets that context; a refusal keeps it and hides suggestions.
    out = ask("nonsense", state)
    assert seen[-1].field_name == "East 80"
    assert out[4] == state
    assert out[5]["visible"] is False and not any(b["visible"] for b in out[6:])


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
    assert "Prerequisites loaded" in html and "6 of 6" in html
    assert web_app.status_panels() == ("", html)  # at the bottom

    monkeypatch.setattr(web_app, "check_model_pulled", lambda pulled: _check("gemma", False))
    html = web_app.status_html()
    assert html.startswith('<details class="pf-status-wrap" open>')
    assert "1 of 6 need attention" in html and "do the thing" in html
    assert web_app.status_panels() == (html, "")  # at the top


def test_example_groups_start_collapsed(tmp_path):
    app = build_app(tmp_path / "audit.jsonl", _fake_pools(tmp_path))
    accordions = [b for b in app.blocks.values() if type(b).__name__ == "Accordion"]
    assert len(accordions) == len(EXAMPLES)
    assert all(a.open is False for a in accordions)
    assert accordions[0].label == "Bad field or bad year? (3)"


def test_each_farm_has_its_own_servers_started_only_when_picked(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "answer_question", _fake_answer([]))
    made: list = []
    ask = make_ask(tmp_path / "audit.jsonl", _fake_pools(tmp_path, made))

    out = ask("Was east 80 a bad field or just a bad year?", None)  # default farm
    assert made == ["farm1"]
    assert "Farm 1" in out[0] and "clean records" in out[0]

    out = ask("Was east 80 a bad field or just a bad year?", None, "farm2")
    assert made == ["farm1", "farm2"]  # Farm 2 only once someone picks it
    assert "Farm 2" in out[0] and "messy records" in out[0] and "Farm 1" not in out[0]

    ask("nonsense", None, "farm2")  # every answer, refusals too, names its farm
    assert made == ["farm1", "farm2"]
    assert "Farm 2" in ask("nonsense", None, "farm2")[0]


def test_farms_point_the_servers_at_their_own_records():
    farm1, farm2 = FARMS["farm1"], FARMS["farm2"]
    assert farm1.data_dir != farm2.data_dir
    assert farm1.confirm_store != farm2.confirm_store
    assert farm2.data_dir.name == "synthetic"  # the existing data, and its evals, are Farm 2
    assert set(farm1.server_env()) == {"FARM_DATA_DIR", "FARM_CONFIRM_STORE"}


def test_status_checks_both_farms(monkeypatch):
    monkeypatch.setattr(web_app, "check_ollama_running", lambda: (_check("Ollama", True), []))
    monkeypatch.setattr(web_app, "check_model_pulled", lambda pulled: _check("gemma", True))
    monkeypatch.setattr(web_app, "check_synthetic_data", lambda d: _check("data", "clean" not in str(d)))
    monkeypatch.setattr(web_app, "check_confirmed_mappings", lambda d: _check("ingest", True))
    html = web_app.status_html()
    assert "Farm 1 data generated" in html and "Farm 2 data generated" in html
    assert "--clean --out data/synthetic-clean" in html  # the fix names Farm 1's command


def test_how_it_works_strip_is_gone(tmp_path):
    # Removed to declutter the page: the answer card and "How we checked it"
    # already show which part came from the records and which from the AI.
    import farm_web.banner as banner

    assert not hasattr(banner, "HOW_IT_WORKS_HTML")
    assert "pf-steps" not in build_app(tmp_path / "audit.jsonl").config.__repr__()


def test_one_example_shows_a_withheld_sentence():
    groups = dict(EXAMPLES)
    assert groups["When the AI is stopped"] == ("Was East 80 a bad field or just a bad year?",)
