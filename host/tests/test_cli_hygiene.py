"""Eval-fix P4: CLI and demo hygiene. Model-free -- none of these reach Ollama."""

from __future__ import annotations

import asyncio

import pytest

from farm_host import cli
from farm_host.mcp_client import (
    DEFAULT_CHILD_ENV,
    START_TIMEOUT_ENV,
    MCPFleet,
    ServerStartTimeout,
    _params_for,
    _start_timeout_from_env,
)


@pytest.mark.parametrize("argv", [[""], ["   "], ["", "  "]])
def test_blank_question_refused_without_a_model_call(argv, tmp_path, monkeypatch, capsys):
    def boom(*_a, **_k):
        raise AssertionError("parse_question must not run for a blank question")

    monkeypatch.setattr(cli, "parse_question", boom)
    code = cli.main([*argv, "--audit-log", str(tmp_path / "audit.jsonl")])
    assert code == 1
    assert "Provide a question" in capsys.readouterr().out


def test_server_children_get_no_banner_and_no_update_check():
    env = _params_for("field-registry").env
    assert env["FASTMCP_SHOW_SERVER_BANNER"] == "false"
    assert env["FASTMCP_CHECK_FOR_UPDATES"] == "off"
    assert env["FASTMCP_LOG_LEVEL"] == "WARNING"


def test_env_overrides_merge_on_top_of_defaults():
    env = _params_for("field-registry", env={"FARM_DATA_DIR": "/x"}).env
    assert env["FARM_DATA_DIR"] == "/x"
    for key, value in DEFAULT_CHILD_ENV.items():
        assert env[key] == value


def test_start_timeout_default_and_env_override(monkeypatch):
    monkeypatch.delenv(START_TIMEOUT_ENV, raising=False)
    assert _start_timeout_from_env() == 120.0
    monkeypatch.setenv(START_TIMEOUT_ENV, "30")
    assert _start_timeout_from_env() == 30.0
    monkeypatch.setenv(START_TIMEOUT_ENV, "not-a-number")
    assert _start_timeout_from_env() == 120.0


def test_server_that_never_starts_times_out_with_preflight_hint(monkeypatch):
    async def never(self):
        await asyncio.sleep(3600)

    monkeypatch.setattr("mcp.ClientSession.initialize", never)

    async def run():
        async with MCPFleet(["field-registry"], start_timeout=0.5):
            pass

    with pytest.raises(ServerStartTimeout) as info:
        asyncio.run(run())
    message = str(info.value)
    assert "field-registry" in message
    assert "farm-preflight" in message


def test_cli_prints_start_timeout_instead_of_a_traceback(tmp_path, monkeypatch, capsys):
    async def fake_answer(question, audit_log):
        raise ServerStartTimeout("field-registry", 120)

    monkeypatch.setattr(cli, "answer_question", fake_answer)
    code = cli.main(["was east 80 a bad year", "--audit-log", str(tmp_path / "a.jsonl")])
    assert code == 1
    assert "didn't start within 120s" in capsys.readouterr().out
