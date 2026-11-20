"""answer_question's message branching on ParseFailure.kind: a dead
Ollama and a genuinely out-of-scope question must produce visibly different,
correctly-targeted messages. Parse_question is monkeypatched here rather
than actually killing Ollama -- this is testing cli.py's branching logic,
not query_parser.py's classification (that's covered live in
model/tests/test_model_bounded.py).
"""


import pytest

from farm_core.audit import AuditLog
from farm_host import cli
from farm_model.query_parser import ParseFailure


async def test_model_unreachable_message_points_to_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(
            raw_question=question, reason="model call failed: boom", kind="model_unreachable"
        ),
    )
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    result = await cli.answer_question("was the north eighty a bad field or a bad year", audit_log)
    assert not result.ok
    assert "farm-preflight" in result.text
    assert "supported lookup" not in result.text


async def test_out_of_scope_message_does_not_mention_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(
            raw_question=question,
            reason="question is out of scope for v1 (retrospective lookups only)",
            kind="out_of_scope",
        ),
    )
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    result = await cli.answer_question("what will next year's yield be", audit_log)
    assert not result.ok
    assert "supported lookup" in result.text
    assert "farm-preflight" not in result.text


@pytest.mark.parametrize(
    "kind",
    ["model_unreachable", "invalid_output", "out_of_range", "out_of_scope", "season_not_named"],
)
async def test_refusal_kind_is_the_parsers_own_kind(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(raw_question=question, reason="r", kind=kind),
    )
    result = await cli.answer_question("q", AuditLog(tmp_path / "audit.jsonl"))
    assert not result.ok
    assert result.refusal_kind == kind


async def test_season_not_named_asks_for_the_year(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(
            raw_question=question, reason="no year", kind="season_not_named"
        ),
    )
    result = await cli.answer_question("how dry was it", AuditLog(tmp_path / "audit.jsonl"))
    assert "naming the year" in result.text


async def test_numeric_name_refusal_gives_a_grower_friendly_hint(tmp_path, monkeypatch):
    """The "-5.16" follow-up: a refusal (not an answer) that tells the grower
    what to ask instead, never a raw "no field named '-5.16'" error.
    """
    from farm_model.query_parser import NUMERIC_NAME_REASON

    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(
            raw_question=question, reason=NUMERIC_NAME_REASON, kind="out_of_scope"
        ),
    )
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    result = await cli.answer_question("What is the seasonal effect of -5.16?", audit_log)
    assert not result.ok
    assert "can't explain terms or numbers yet" in result.text
    assert "Try asking about a field and season" in result.text
    assert "not_found" not in result.text


@pytest.mark.ollama
async def test_successful_query_reports_ok(tmp_path):
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    result = await cli.answer_question("was the north eighty a bad field or a bad year", audit_log)
    assert result.ok
    assert result.text
    assert "Therefore:" in result.text


def test_main_exits_nonzero_on_refusal(tmp_path, monkeypatch):
    async def fake_answer_question(question, audit_log, env_overrides=None):
        return cli.AnswerResult(text="refused", ok=False)

    monkeypatch.setattr(cli, "answer_question", fake_answer_question)
    exit_code = cli.main(["some", "question", "--audit-log", str(tmp_path / "audit.jsonl")])
    assert exit_code == 1


def test_main_exits_zero_on_success(tmp_path, monkeypatch):
    async def fake_answer_question(question, audit_log, env_overrides=None):
        return cli.AnswerResult(text="a real answer", ok=True)

    monkeypatch.setattr(cli, "answer_question", fake_answer_question)
    exit_code = cli.main(["some", "question", "--audit-log", str(tmp_path / "audit.jsonl")])
    assert exit_code == 0


PYDANTIC_ERROR = (
    "1 validation error for QueryObject\n  Value error, which_fields_made_money requires "
    "either 'seasons' (explicit years) or 'season_count_from_latest' (a relative window) "
    "[type=value_error] For further information visit https://errors.pydantic.dev/2.14/v/value_error"
)


@pytest.mark.parametrize(
    "kind", ["invalid_output", "out_of_scope", "out_of_range", "season_not_named", "unresolved_followup"]
)
async def test_raw_reason_never_reaches_the_grower(tmp_path, monkeypatch, kind):
    """The screenshot bug (2026-11-20): a pydantic error was printed in the
    answer. The reason goes to the audit log; the grower sees a plain sentence."""
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(raw_question=question, reason=PYDANTIC_ERROR, kind=kind),
    )
    log = AuditLog(tmp_path / "audit.jsonl")
    result = await cli.answer_question("which fields?", log)
    assert not result.ok
    for leak in ("validation error", "pydantic", "Reason:", "season_count_from_latest"):
        assert leak not in result.text
    refused = [e for e in log.entries() if e["event"] == "parse_refused"]
    assert refused[0]["reason"] == PYDANTIC_ERROR


async def test_unmatched_question_points_to_what_can_i_ask(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_question",
        lambda question, seasons: ParseFailure(raw_question=question, reason="x", kind="invalid_output"),
    )
    result = await cli.answer_question("hmm", AuditLog(tmp_path / "audit.jsonl"))
    assert "What can I ask?" in result.text
