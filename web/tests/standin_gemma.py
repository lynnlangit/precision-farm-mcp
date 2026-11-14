"""A stand-in for Gemma, so the web app's question box can be tested anywhere.

Only the two model calls are replaced -- the question parser and the
narrator's one extra sentence. Everything else is real: the MCP servers, the
farm records, every check, the audit log and the Gradio page. The stand-in
answers like gemma3:4b does on Lynn's Mac for the questions below, including
the one that is withheld (eval 2, where the model blames "an unusual weather
pattern" that no record shows).

    uv run --project web python web/tests/standin_gemma.py --no-browser --port 7861

STANDIN_DELAY (seconds, default 1.0) is how long each fake model call takes,
so a double click lands while the first question is still being answered.
"""

from __future__ import annotations

import json
import os
import sys
import time
from types import SimpleNamespace

import ollama

# question (lower case, no trailing "?") -> what the parser returns.
PARSES: dict[str, dict] = {
    "was east 80 a bad field or just a bad year": {
        "intent": "bad_field_or_bad_year", "field_name": "East 80"},
    "was the marginal eighty a bad field or just a bad year": {
        "intent": "bad_field_or_bad_year", "field_name": "Marginal Eighty"},
    "was south 160 south a bad field or just a bad year": {
        "intent": "bad_field_or_bad_year", "field_name": "South 160 South"},
    "which fields made money in the last five years": {
        "intent": "which_fields_made_money", "season_count_from_latest": 5},
    "which fields made money in 2019 and 2020": {
        "intent": "which_fields_made_money", "seasons": [2019, 2020]},
    "how dry was 2018": {"intent": "season_weather", "season": 2018},
    "what did i put on coulee field in 2023": {
        "intent": "applied_inputs", "field_name": "Coulee Field", "season": 2023},
    "does the seed cost on sheyenne bottom in 2022 look right": {
        "intent": "cost_reconciliation", "field_name": "Sheyenne Bottom", "season": 2022},
    # Negative: parses fine, but no field by that name is in the records.
    "was imaginary quarter a bad field or just a bad year": {
        "intent": "bad_field_or_bad_year", "field_name": "Imaginary Quarter"},
}

# question -> the one extra sentence the model offers ("NONE" = nothing to add).
NARRATIONS: dict[str, str] = {
    # What gemma3:4b writes on Lynn's Mac: fails "doesn't name a cause".
    "was east 80 a bad field or just a bad year": (
        "East 80's poor 2020 season was likely caused by an unusual weather pattern."
    ),
}

CALLS: list[dict] = []


def _key(text: str) -> str:
    return " ".join(text.strip().lower().rstrip("?").split())


def fake_chat(model=None, messages=None, format=None, options=None, **_):
    time.sleep(float(os.environ.get("STANDIN_DELAY", "1.0")))
    messages = messages or []
    if format is not None:  # the question parser asks for JSON in a schema
        question = messages[-1]["content"]
        CALLS.append({"call": "parse", "question": question})
        content = json.dumps(PARSES.get(_key(question), {"intent": "unrecognized"}))
    else:  # the narrator: the question is quoted somewhere in its prompt
        prompt = _key(messages[-1]["content"])
        content = next((s for q, s in NARRATIONS.items() if q in prompt), "NONE")
        CALLS.append({"call": "narrate"})
    return SimpleNamespace(message=SimpleNamespace(content=content))


def install() -> None:
    """Swap Gemma for the stand-in (both modules call ollama.chat)."""
    ollama.chat = fake_chat


def main(argv: list[str] | None = None) -> int:
    install()
    from farm_web import app as web_app

    # The preflight's "is Ollama running / is gemma pulled" check: pretend yes.
    from farm_host.preflight_cli import CheckResult

    ok = CheckResult(name="Ollama running (stand-in)", ok=True, detail="stand-in Gemma")
    web_app.check_ollama_running = lambda: (ok, ["gemma3:4b"])
    web_app.check_model_pulled = lambda pulled: CheckResult(
        name="gemma3:4b pulled (stand-in)", ok=True, detail="stand-in Gemma"
    )
    return web_app.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
