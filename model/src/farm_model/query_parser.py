"""Job 1 of Gemma's two jobs: turn a natural-language question into a
QueryObject. Generation is constrained to QueryObject's JSON schema at decode
time (Ollama's structured-output support), then re-validated with Pydantic,
then checked against the known season range -- three independent gates
before anything reaches the host. Anything that doesn't clear all three comes
back as a ParseFailure, never a best-effort guess.

The model never resolves a field name itself -- it passes through whatever
string the farmer used (however misspelled or drifted) and leaves resolving
it to the host's alias table (field-registry). That's a structural choice,
not an instruction: this module has no import of, or access to, the alias
table at all.
"""

from __future__ import annotations

import dataclasses

import ollama
from pydantic import ValidationError

from .query_schema import QueryIntent, QueryObject, resolve_relative_seasons

DEFAULT_MODEL = "gemma3:4b"

_SYSTEM_PROMPT_TEMPLATE = """You turn a farmer's question about their own field \
records into a QueryObject. You do not answer the question -- you only select \
which lookup to run and its parameters. You never compute or state a number, \
and you never compute which years a phrase like "last five years" means.

Known seasons: {known_seasons}

Choose exactly one intent:
- which_fields_made_money: ranks every field by total profit. If the farmer \
named specific years (e.g. "2019 and 2020", "in 2022"), put exactly those \
numbers in "seasons" -- never season_count_from_latest for named years. If \
the farmer used a relative phrase instead ("last five years", "last \
season", "the past three seasons"), put ONLY the count in \
"season_count_from_latest" (5, 1, or 3) -- do NOT pick which years yourself. \
If neither is stated, leave both empty.
  Example: "how did 2019 and 2020 compare" -> seasons=[2019, 2020].
  Example: "last three years" -> season_count_from_latest=3, seasons=null.
- bad_field_or_bad_year: classifies one field's profit history. The phrasing \
"was X a bad field or a bad year" / "was X a bad field or just a bad year" \
is ALWAYS this intent, never explain_shortfall, even though it contains the \
words "bad year". Requires "field_name" exactly as the farmer said it.
- resolve_field_name: looks up what a name meant in a specific season. \
Requires "raw_name" and "season".
- yield_reconciliation: compares yield monitor vs scale ticket totals for \
one field/season. Requires "field_name" and "season".
- cost_reconciliation: compares ledger costs vs as-applied-derived costs for \
one field/season. Requires "field_name" and "season".
- explain_shortfall: only for a question starting with "why" or "what \
caused", e.g. "why was X a bad year". Requires "field_name" exactly as the \
farmer said it.
- unrecognized: the question asks for something else entirely -- a \
prediction, a recommendation, a yield forecast, a prescription map, anything \
not a lookup against past records. Use this rather than forcing a fit.

Only use "field_name" you'll see the farmer mention -- never invent or correct
a spelling.
"""


@dataclasses.dataclass(frozen=True)
class ParseFailure:
    raw_question: str
    reason: str
    raw_model_output: str | None = None


def parse_question(
    question: str,
    known_seasons: list[int],
    model: str = DEFAULT_MODEL,
) -> QueryObject | ParseFailure:
    schema = QueryObject.model_json_schema()
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(known_seasons=known_seasons)

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            format=schema,
            options={"temperature": 0},
        )
    except Exception as e:  # noqa: BLE001 -- any transport/model failure is a parse failure
        return ParseFailure(raw_question=question, reason=f"model call failed: {e}")

    raw_output = response.message.content or ""
    try:
        query = QueryObject.model_validate_json(raw_output)
    except (ValidationError, ValueError) as e:
        return ParseFailure(raw_question=question, reason=str(e), raw_model_output=raw_output)

    if query.intent == QueryIntent.UNRECOGNIZED:
        return ParseFailure(
            raw_question=question,
            reason="question is out of scope for v1 (retrospective lookups only)",
            raw_model_output=raw_output,
        )

    all_seasons_in_query = (query.seasons or []) + ([query.season] if query.season else [])
    out_of_range_seasons = [s for s in all_seasons_in_query if s not in known_seasons]
    if out_of_range_seasons:
        return ParseFailure(
            raw_question=question,
            reason=f"season(s) {out_of_range_seasons} are outside the known range {known_seasons}",
            raw_model_output=raw_output,
        )

    if query.intent == QueryIntent.WHICH_FIELDS_MADE_MONEY:
        # Deterministic resolution, not the model's arithmetic: turn a
        # relative window (or no window at all) into concrete years here,
        # in plain Python, against the host's own known season range.
        query = query.model_copy(
            update={"seasons": resolve_relative_seasons(query, known_seasons)}
        )

    return query
