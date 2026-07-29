"""Job 2 of Gemma's two jobs: turn a host-computed result into plain
language. This function receives only the already-computed JSON payload --
never a database handle, an MCP client, or any tool -- so there is nothing
for it to compute even if it tried. verification.py is what proves that.
"""

from __future__ import annotations

import json

import ollama

from .verification import check_narration_grounded, check_verdict_not_contradicted

DEFAULT_MODEL = "gemma3:4b"

_NARRATION_PROMPT_TEMPLATE = """The farmer asked: "{question}"

Here is the exact computed answer, already produced by deterministic code. \
These numbers are correct and final -- do not perform any arithmetic, do \
not recompute anything, and do not state any number that isn't shown below. \
If a "verdict" field is present, your answer must agree with it exactly -- \
never conclude the opposite of what "verdict" says.

{payload_json}

Write a short, plain-language answer (2-4 sentences) for the farmer, using \
only the facts and numbers above."""

_RETRY_SUFFIX = """

Your previous attempt either stated a number not shown above or drew a \
conclusion that contradicts the "verdict" field. Try again, more literally: \
state the verdict's plain meaning directly and only cite numbers copied \
from the JSON above."""


def narrate(question: str, result_payload: dict, model: str = DEFAULT_MODEL) -> str:
    """One narration attempt, no verification. narrate_verified() below is
    what the CLI actually uses -- prefer that unless you're deliberately
    testing the raw model output.
    """
    prompt = _NARRATION_PROMPT_TEMPLATE.format(
        question=question, payload_json=json.dumps(result_payload, indent=2, default=str)
    )
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2},
    )
    return response.message.content or ""


def _deterministic_fallback(question: str, payload: dict) -> str:
    """Guaranteed-correct, template-built sentence used only when the model's
    narration fails verification twice. No LLM involved -- this is the safety
    net under the safety net.
    """
    if "verdict" in payload:
        field = payload.get("field_name", "this field")
        evidence = payload.get("evidence", {})
        if payload["verdict"] == "bad_field":
            return (
                f"{field} lost money in {evidence.get('loss_rate', 0) * 100:.0f}% of "
                f"{evidence.get('num_seasons', '?')} recorded seasons -- a chronic "
                "pattern, not a single bad year."
            )
        if payload["verdict"] == "bad_year":
            seasons = evidence.get("outlier_seasons", [])
            return (
                f"{field} was profitable most seasons (median "
                f"${evidence.get('median_profit_per_acre', 0):,.2f}/ac), except for a "
                f"clear outlier in {', '.join(str(s) for s in seasons)} -- a bad year, "
                "not a bad field."
            )
        return (
            f"{field} shows no chronic loss pattern (median "
            f"${evidence.get('median_profit_per_acre', 0):,.2f}/ac) across "
            f"{evidence.get('num_seasons', '?')} recorded seasons."
        )
    if "results" in payload and payload["results"]:
        top = payload["results"][0]
        return (
            f"{top.get('display_name', 'The top field')} had the highest profit: "
            f"${top.get('total_profit', 0):,.2f} over {top.get('seasons', [])}."
        )
    return "The computed result is available, but a plain-language summary could not be verified."


def narrate_verified(
    question: str, result_payload: dict, model: str = DEFAULT_MODEL, max_attempts: int = 2
) -> str:
    """narrate(), then verify the result is both numerically grounded and
    doesn't contradict the payload's own verdict. Retries once with a
    stronger prompt; if verification still fails, falls back to a
    deterministic template rather than showing an unverified narration.
    """
    prompt = _NARRATION_PROMPT_TEMPLATE.format(
        question=question, payload_json=json.dumps(result_payload, indent=2, default=str)
    )
    for attempt in range(max_attempts):
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2},
        )
        narration = response.message.content or ""
        grounding = check_narration_grounded(narration, result_payload, question=question)
        consistent = check_verdict_not_contradicted(narration, result_payload)
        if grounding.is_grounded and consistent:
            return narration
        prompt += _RETRY_SUFFIX

    return _deterministic_fallback(question, result_payload)
