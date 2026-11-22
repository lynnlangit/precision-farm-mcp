"""Model-free: the speed settings (keep_alive, the narration cap, warm-up)
and the timing record that goes on the audit log."""

from __future__ import annotations

import json
import types

from farm_model import narrator, ollama_settings, query_parser
from farm_model.ollama_settings import (
    KEEP_ALIVE,
    NARRATION_MAX_TOKENS,
    record,
    start_timing,
    timings_for,
    warm_up,
)


def _reply(content: str, **timing):
    return types.SimpleNamespace(message=types.SimpleNamespace(content=content), **timing)


def test_record_converts_ollama_nanoseconds_to_seconds():
    timings = start_timing()
    record("parse", _reply("{}", load_duration=12_000_000, prompt_eval_duration=1_500_000_000,
                           eval_duration=2_250_000_000, total_duration=3_800_000_000,
                           prompt_eval_count=1012, eval_count=58))
    assert timings_for(timings, "parse") == [
        {"load_s": 0.01, "read_s": 1.5, "write_s": 2.25, "total_s": 3.8,
         "read_tokens": 1012, "write_tokens": 58}
    ]
    assert timings_for(timings, "narrate") == []


def test_record_skips_a_stub_without_timings_and_outside_a_question():
    timings = start_timing()
    record("parse", _reply("{}"))
    assert timings == []
    ollama_settings._TIMINGS.set(None)
    record("parse", _reply("{}", total_duration=1))  # no error, nowhere to put it


def test_parser_keeps_the_model_loaded(monkeypatch):
    seen = {}

    def fake_chat(model, messages, format, options, **kw):  # noqa: A002
        seen.update(kw, options=options)
        return _reply(json.dumps({"intent": "season_weather", "season": 2018}))

    monkeypatch.setattr(query_parser.ollama, "chat", fake_chat)
    query_parser.parse_question("How dry was 2018?", list(range(2016, 2026)))
    assert seen["keep_alive"] == KEEP_ALIVE
    assert seen["options"] == {"temperature": 0}  # the parse itself is unchanged


def test_narration_is_capped_and_keeps_the_model_loaded(monkeypatch):
    seen = {}

    def fake_chat(model, messages, options, **kw):
        seen.update(kw, options=options)
        return _reply("NONE")

    monkeypatch.setattr(narrator.ollama, "chat", fake_chat)
    narrator.narrate("How dry was 2018?", {"season": 2018})
    assert seen["keep_alive"] == KEEP_ALIVE
    assert seen["options"]["num_predict"] == NARRATION_MAX_TOKENS
    # Same sampling as before the cap: same seed, same temperature.
    assert seen["options"]["seed"] == narrator.NARRATION_SEED
    assert seen["options"]["temperature"] == 0.2


def test_warm_up_is_best_effort(monkeypatch):
    calls = []

    def ok(**kw):
        calls.append(kw)

    def down(**kw):
        raise ConnectionError("Ollama is not running")

    monkeypatch.setattr(ollama_settings.ollama, "generate", ok)
    assert warm_up("gemma3:4b") is True
    assert calls == [{"model": "gemma3:4b", "prompt": "", "keep_alive": KEEP_ALIVE}]
    monkeypatch.setattr(ollama_settings.ollama, "generate", down)
    assert warm_up("gemma3:4b") is False
