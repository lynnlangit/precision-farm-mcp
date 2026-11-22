"""Ollama settings that change how fast an answer comes back, never what it
says, plus a record of Ollama's own timings for the audit log.

- KEEP_ALIVE: how long Ollama keeps the model in memory after a call.
  Ollama's default is 5 minutes, so a pause in a grower session meant the
  next question waited for the model to reload.
- NARRATION_MAX_TOKENS: a cap on the narration call. Only the first
  sentence is ever kept, and one sentence is far shorter than this, so the
  cap only stops a model that keeps writing after it.
- warm_up(): loads the model with an empty request, so the first question
  doesn't wait for it (the web app calls it at start).
- start_timing() / record(): each model call adds Ollama's own load, read
  and write times; farm_host.cli puts them on the audit log entries.
"""

from __future__ import annotations

import contextvars

import ollama

KEEP_ALIVE = "60m"
NARRATION_MAX_TOKENS = 120

_TIMINGS: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "farm_model_timings", default=None
)

# Ollama reports durations in nanoseconds.
_DURATIONS = {
    "load_duration": "load_s",
    "prompt_eval_duration": "read_s",
    "eval_duration": "write_s",
    "total_duration": "total_s",
}
_COUNTS = {"prompt_eval_count": "read_tokens", "eval_count": "write_tokens"}


def start_timing() -> list[dict]:
    """Start a fresh list for one question; record() appends to it."""
    timings: list[dict] = []
    _TIMINGS.set(timings)
    return timings


def record(job: str, response) -> None:
    """Add one call's timings ("parse" or "narrate"). Does nothing outside
    start_timing(), or when the response carries no timings (a test stub)."""
    timings = _TIMINGS.get()
    if timings is None:
        return
    entry: dict = {"job": job}
    for attr, key in _DURATIONS.items():
        value = getattr(response, attr, None)
        if isinstance(value, int):
            entry[key] = round(value / 1e9, 2)
    for attr, key in _COUNTS.items():
        value = getattr(response, attr, None)
        if isinstance(value, int):
            entry[key] = value
    if len(entry) > 1:
        timings.append(entry)


def timings_for(timings: list[dict], job: str) -> list[dict]:
    return [{k: v for k, v in t.items() if k != "job"} for t in timings if t["job"] == job]


def warm_up(model: str) -> bool:
    """Load `model` into memory now. False (and nothing raised) when Ollama
    isn't reachable or the model isn't pulled: the first question then
    reports that the usual way."""
    try:
        ollama.generate(model=model, prompt="", keep_alive=KEEP_ALIVE)
    except Exception:  # noqa: BLE001 -- warming is best effort
        return False
    return True
