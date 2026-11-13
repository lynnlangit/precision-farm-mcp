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
import re
from typing import Literal

import ollama
from pydantic import ValidationError

from .query_schema import FollowUpContext, QueryIntent, QueryObject, resolve_relative_seasons

# Distinguishes "Ollama/the model itself isn't in a working state" from
# "the model ran fine and the question just doesn't map to anything v1
# answers" -- host/src/farm_host/cli.py uses this to give the farmer an
# actionable, correctly-targeted message instead of one generic refusal for
# both. "model_unreachable" covers both a dead Ollama daemon (ConnectionError)
# and a not-pulled model (ollama.ResponseError) -- from the farmer's side
# both are "something about the environment isn't ready", not "reword your
# question".
#
# "unresolved_followup": a follow-up's field or season came from neither the
# new question nor the carried context (or a year the farmer named was
# dropped) -- refuse rather than answer what may be the wrong question.
ParseFailureKind = Literal[
    "model_unreachable", "invalid_output", "out_of_range", "out_of_scope", "unresolved_followup"
]

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
one field/season. Requires "field_name" and "season". A question asking \
whether a cost line item (seed, fertilizer, chemical, fuel, cash rent) \
"looks right", "is correct", "seems off" or "seems high/low" for a field and \
season is ALWAYS this intent, never bad_field_or_bad_year, even though it \
names a field.
  Example: "Does the seed cost on Riverside in 2022 look right?" -> \
field_name="Riverside", season=2022.
  Example: "Is the fertilizer cost for East 80 in 2019 correct?" -> \
field_name="East 80", season=2019.
  Example: "The chemical cost on Home Quarter in 2021 seems off" -> \
field_name="Home Quarter", season=2021.
- explain_shortfall: only for a question starting with "why" or "what \
caused", e.g. "why was X a bad year". Requires "field_name" exactly as the \
farmer said it.
- zone_profitability: asks about PART of one named field, e.g. "which part \
of X is losing money", "is any part of X unprofitable". Requires \
"field_name" and "season".
- unprofitable_zones_in_profitable_fields: asks about the WHOLE farm, no \
field named, e.g. "what share of acres are losing money in otherwise good \
fields". Requires nothing.
- unrecognized: the question asks for something else entirely -- a \
prediction, a recommendation, a yield forecast, a prescription map, anything \
not a lookup against past records. Use this rather than forcing a fit.

Only use "field_name" you'll see the farmer mention -- never invent or correct
a spelling.
"""

# Appended only for a follow-up. Deliberately just the last question's field,
# season and type -- never earlier answers or their numbers.
_FOLLOW_UP_TEMPLATE = """
This question follows an earlier one. The earlier question was about:
{context}
If this question leaves out the field, the season, or what kind of lookup it \
is (e.g. "what about East 80?", "and in 2023?", "why?"), take the missing \
part from the earlier question. If it names a different field or year, use \
the new one exactly as the farmer said it. Never take a number from the \
earlier question other than its season.
"""

# Years written in the question, e.g. "2023" -- compared against the parsed
# query so a follow-up can't silently keep the earlier season.
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[\"'“”‘’?.,!]", " ", text.lower()).split())


def _check_follow_up(
    question: str, query: QueryObject, context: FollowUpContext, known_seasons: list[int]
) -> str | None:
    """Code-level check that a follow-up's parameters came from somewhere real.

    Every field name and season in the parsed query must either appear in
    the new question or equal the carried context; and every known year the
    farmer wrote in the new question must actually be used. Returns the
    reason to refuse, or None. This is a check on the model, not a prompt
    instruction to it.
    """
    q = _normalize(question)
    for name in (query.field_name, query.raw_name):
        if name is None:
            continue
        in_question = _normalize(name) in q
        from_context = context.field_name is not None and _normalize(name) == _normalize(
            context.field_name
        )
        if not (in_question or from_context):
            return f"the field {name!r} is neither in this question nor the earlier one"

    named_years = {int(m.group(0)) for m in _YEAR.finditer(question)} & set(known_seasons)
    # Checked before a relative window ("last five years") is resolved, so
    # season_count_from_latest leaves `used` empty here -- that resolution is
    # done in code against the known range, never by the model.
    used = set(query.seasons or []) | ({query.season} if query.season else set())
    for season in used:
        if season not in named_years and season != context.season:
            return f"the season {season} is neither in this question nor the earlier one"
    takes_seasons = query.intent in (
        QueryIntent.WHICH_FIELDS_MADE_MONEY,
        QueryIntent.ZONE_PROFITABILITY,
        QueryIntent.RESOLVE_FIELD_NAME,
        QueryIntent.YIELD_RECONCILIATION,
        QueryIntent.COST_RECONCILIATION,
    )
    dropped = sorted(named_years - used)
    if takes_seasons and dropped:
        return f"the question names {dropped}, but the lookup would have used {sorted(used)}"
    return None


# A field name is never just a number. "-5.16" or "2020" in field_name /
# raw_name means the model mistook a number from the question (often a value
# from a previous answer) for a field -- refuse in code rather than trusting a
# prompt instruction. Names that merely contain digits ("East 80",
# "Township Rd 12") are unaffected.
_NUMERIC_NAME = re.compile(r"^\s*[+-]?(\d+(\.\d*)?|\.\d+)\s*$")

NUMERIC_NAME_REASON = (
    "that looks like a number, not a field name -- I can look up records, "
    "but I can't explain terms or numbers yet"
)


def _is_numeric_name(name: str | None) -> bool:
    return name is not None and bool(_NUMERIC_NAME.match(name))


@dataclasses.dataclass(frozen=True)
class ParseFailure:
    raw_question: str
    reason: str
    kind: ParseFailureKind
    raw_model_output: str | None = None


def parse_question(
    question: str,
    known_seasons: list[int],
    model: str = DEFAULT_MODEL,
    context: FollowUpContext | None = None,
) -> QueryObject | ParseFailure:
    schema = QueryObject.model_json_schema()
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(known_seasons=known_seasons)
    if context is not None and context.is_empty():
        context = None
    if context is not None:
        system_prompt += _FOLLOW_UP_TEMPLATE.format(context=context.prompt_block())

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
    except (ConnectionError, ollama.ResponseError) as e:
        # Ollama isn't running, or the model isn't pulled -- an environment
        # problem, not a question the farmer needs to reword.
        return ParseFailure(
            raw_question=question, reason=f"model call failed: {e}", kind="model_unreachable"
        )
    except Exception as e:  # noqa: BLE001 -- any other transport/model failure is still unreachable
        return ParseFailure(
            raw_question=question, reason=f"model call failed: {e}", kind="model_unreachable"
        )

    raw_output = response.message.content or ""
    try:
        query = QueryObject.model_validate_json(raw_output)
    except (ValidationError, ValueError) as e:
        return ParseFailure(
            raw_question=question, reason=str(e), kind="invalid_output", raw_model_output=raw_output
        )

    if query.intent == QueryIntent.UNRECOGNIZED:
        return ParseFailure(
            raw_question=question,
            reason="question is out of scope for v1 (retrospective lookups only)",
            kind="out_of_scope",
            raw_model_output=raw_output,
        )

    if _is_numeric_name(query.field_name) or _is_numeric_name(query.raw_name):
        return ParseFailure(
            raw_question=question,
            reason=NUMERIC_NAME_REASON,
            kind="out_of_scope",
            raw_model_output=raw_output,
        )

    all_seasons_in_query = (query.seasons or []) + ([query.season] if query.season else [])
    out_of_range_seasons = [s for s in all_seasons_in_query if s not in known_seasons]
    if out_of_range_seasons:
        return ParseFailure(
            raw_question=question,
            reason=f"season(s) {out_of_range_seasons} are outside the known range {known_seasons}",
            kind="out_of_range",
            raw_model_output=raw_output,
        )

    if context is not None:
        reason = _check_follow_up(question, query, context, known_seasons)
        if reason:
            return ParseFailure(
                raw_question=question,
                reason=reason,
                kind="unresolved_followup",
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
