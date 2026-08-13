"""answer_question's message branching on ParseFailure.kind (item 1): a dead
Ollama and a genuinely out-of-scope question must produce visibly different,
correctly-targeted messages. Parse_question is monkeypatched here rather
than actually killing Ollama -- this is testing cli.py's branching logic,
not query_parser.py's classification (that's covered live in
model/tests/test_model_bounded.py).
"""

from pathlib import Path

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
