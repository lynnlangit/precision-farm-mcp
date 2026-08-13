"""The model-free query path (item 4): --intent bypasses parse_question and
narrate_verified entirely, so it must produce the same tool-call result as
the natural-language path (the established "wrapping must not change a
number" pattern) while making zero calls to ollama.chat.
"""

import pytest

from farm_core.audit import AuditLog
from farm_core.profitability import bad_field_or_bad_year
from farm_core.pipeline import load_query_time_snapshot
from farm_host import cli
from farm_host.cli import _build_structured_query, answer_question_structured
from farm_model.query_schema import QueryIntent, QueryObject
from pydantic import ValidationError

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "synthetic"
CONFIRM_STORE_PATH = REPO_ROOT / "data" / "confirmed_mappings.json"


async def test_structured_bad_field_or_bad_year_matches_direct_call(tmp_path):
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    snapshot = load_query_time_snapshot(
        DATA_DIR, CONFIRM_STORE_PATH, AuditLog(tmp_path / "direct_audit.jsonl")
    )
    canonical_id = snapshot.canonical_id_for_name("North Eighty")

    query = QueryObject(intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR, field_name="North Eighty")
    result = await answer_question_structured(query, audit_log)

    assert result.ok
    direct = bad_field_or_bad_year(snapshot.profit_records, canonical_id)
    assert direct["verdict"] in result.text
    assert "Therefore:" in result.text


async def test_structured_path_never_calls_ollama(tmp_path, monkeypatch):
    import ollama

    def fail_if_called(*args, **kwargs):
        raise AssertionError("ollama.chat must never be called on the model-free path")

    monkeypatch.setattr(ollama, "chat", fail_if_called)

    audit_log = AuditLog(tmp_path / "audit.jsonl")
    query = QueryObject(intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR, field_name="North Eighty")
    result = await answer_question_structured(query, audit_log)
    assert result.ok


async def test_structured_path_reports_refusal_for_unknown_field(tmp_path):
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    query = QueryObject(intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR, field_name="Not A Real Field")
    result = await answer_question_structured(query, audit_log)
    assert not result.ok


def test_missing_required_field_raises_validation_error():
    with pytest.raises(ValidationError):
        QueryObject(intent=QueryIntent.ZONE_PROFITABILITY, field_name="North Eighty")  # no season


def test_build_structured_query_resolves_relative_seasons(monkeypatch):
    args = _fake_args(
        intent="which_fields_made_money",
        field_name=None,
        raw_name=None,
        season=None,
        seasons=None,
        season_count_from_latest=3,
    )
    query = _build_structured_query(args)
    assert query.seasons == sorted(query.seasons)
    assert len(query.seasons) == 3


def test_main_list_intents_exits_zero(capsys):
    exit_code = cli.main(["--list-intents"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "zone_profitability" in captured.out
    assert "--field-name" in captured.out


def test_main_structured_intent_invalid_arguments_exits_nonzero(tmp_path, capsys):
    exit_code = cli.main(
        ["--intent", "zone_profitability", "--field-name", "North Eighty", "--audit-log", str(tmp_path / "audit.jsonl")]
    )  # missing --season
    assert exit_code == 1


def test_main_no_question_and_no_intent_exits_nonzero(tmp_path):
    exit_code = cli.main(["--audit-log", str(tmp_path / "audit.jsonl")])
    assert exit_code == 1


def _fake_args(**kwargs):
    class Args:
        pass

    a = Args()
    for k, v in kwargs.items():
        setattr(a, k, v)
    return a
