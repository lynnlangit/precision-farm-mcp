"""What the audit log records about each question, for the web app's Session
history: where it was asked (source, farm, session) and what the grower read
(the green lead and the blue sentence that passed every check). No model and
no servers: the parser, the lookup and the narrator are stand-ins."""

from types import SimpleNamespace

from farm_core.audit import AuditLog
from farm_host import cli
from farm_model.narrator import NarrationOutcome
from farm_model.query_parser import ParseFailure
from farm_model.query_schema import QueryIntent, QueryObject
from farm_model.verification import GroundingResult


class _Fleet:
    async def call(self, server, tool, **args):
        return SimpleNamespace(
            data={"verdict": "bad_year", "field_name": "East 80"}, untrusted_paths=frozenset()
        )


def _stand_ins(monkeypatch, context):
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons, **kw: QueryObject(
            intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR, field_name="East 80"
        ),
    )
    monkeypatch.setattr(
        cli,
        "narrate_verified",
        lambda question, result, untrusted_paths=frozenset(): NarrationOutcome(
            text="lead",
            truncated=False,
            measured_or_derived_grounding=GroundingResult([]),
            modeled_grounding=None,
            attempts_used=1,
            used_fallback=context is None,
            failed_checks=() if context else (("unsupported_cause",),),
            rejected_texts=() if context else ("It was the weather.",),
            lead="East 80 had a bad year.",
            context=context,
        ),
    )


def _by_event(path):
    return {e["event"]: e for e in AuditLog(path).entries()}


async def test_web_question_logs_source_farm_and_session(tmp_path, monkeypatch):
    _stand_ins(monkeypatch, "Its profit was low in 2020.")
    path = tmp_path / "audit.jsonl"
    await cli.answer_question(
        "Was East 80 a bad year?",
        AuditLog(path),
        fleet=_Fleet(),
        source="web",
        farm="farm1",
        session_id="web-1",
    )
    events = _by_event(path)
    assert events["query"]["source"] == "web"
    assert events["query"]["farm"] == "farm1"
    assert events["query"]["session_id"] == "web-1"
    assert events["narration"]["lead"] == "East 80 had a bad year."
    assert events["narration"]["shown_text"] == "Its profit was low in 2020."
    assert AuditLog(path).verify()


async def test_withheld_sentence_is_not_logged_as_shown(tmp_path, monkeypatch):
    _stand_ins(monkeypatch, None)
    path = tmp_path / "audit.jsonl"
    await cli.answer_question("Was East 80 a bad year?", AuditLog(path), fleet=_Fleet())
    narration = _by_event(path)["narration"]
    assert narration["shown_text"] is None
    assert narration["rejected_texts"] == ["It was the weather."]


async def test_cli_question_is_labelled_cli_with_no_farm_or_session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(raw_question=question, reason="r", kind="out_of_scope"),
    )
    path = tmp_path / "audit.jsonl"
    await cli.answer_question("what will it rain", AuditLog(path))
    query = _by_event(path)["query"]
    assert query["source"] == "cli"
    assert "farm" not in query and "session_id" not in query
