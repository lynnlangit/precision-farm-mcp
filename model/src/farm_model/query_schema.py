"""The one schema Gemma's query-parsing job is constrained to. Every intent
maps 1:1 to a host/MCP tool built in Phases 3-4 -- the model can only ever
select from this fixed menu and fill in its parameters, never invent a new
kind of question or compute an answer itself.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, model_validator


class QueryIntent(str, Enum):
    WHICH_FIELDS_MADE_MONEY = "which_fields_made_money"
    BAD_FIELD_OR_BAD_YEAR = "bad_field_or_bad_year"
    EXPLAIN_SHORTFALL = "explain_shortfall"
    RESOLVE_FIELD_NAME = "resolve_field_name"
    YIELD_RECONCILIATION = "yield_reconciliation"
    COST_RECONCILIATION = "cost_reconciliation"
    UNRECOGNIZED = "unrecognized"


# which_fields_made_money accepts EITHER seasons (explicit years) OR
# season_count_from_latest (a relative window like "last five years") -- not
# both required. Resolving "last five years" into concrete years is a
# deterministic computation against the known season range (see
# resolve_relative_seasons below), never the model's own arithmetic: a small
# model asked to compute the window itself gets it wrong just as often as
# right (verified empirically -- gemma3:4b returned five *arbitrary* years
# for "last five years" rather than the five most recent), and the spec is
# explicit that choosing which seasons are included is not the model's call.
_REQUIRED_FIELDS: dict[QueryIntent, tuple[str, ...]] = {
    QueryIntent.WHICH_FIELDS_MADE_MONEY: (),
    QueryIntent.BAD_FIELD_OR_BAD_YEAR: ("field_name",),
    QueryIntent.EXPLAIN_SHORTFALL: ("field_name",),
    QueryIntent.RESOLVE_FIELD_NAME: ("raw_name", "season"),
    QueryIntent.YIELD_RECONCILIATION: ("field_name", "season"),
    QueryIntent.COST_RECONCILIATION: ("field_name", "season"),
    QueryIntent.UNRECOGNIZED: (),
}


class QueryObject(BaseModel):
    """Structured form of a farmer's question. Every field beyond `intent` is
    optional at the JSON-schema level (small models handle a flat optional
    schema far more reliably than a discriminated union), but validated as
    required per-intent here -- an intent missing its required parameter is
    rejected, not guessed at.
    """

    intent: QueryIntent
    field_name: str | None = None
    raw_name: str | None = None
    season: int | None = None
    seasons: list[int] | None = None
    season_count_from_latest: int | None = None

    @model_validator(mode="after")
    def _check_required_fields_for_intent(self) -> QueryObject:
        missing = [f for f in _REQUIRED_FIELDS[self.intent] if getattr(self, f) in (None, [])]
        if missing:
            raise ValueError(
                f"intent {self.intent.value!r} requires {missing}, but they were not provided"
            )
        if self.intent == QueryIntent.WHICH_FIELDS_MADE_MONEY:
            if not self.seasons and not self.season_count_from_latest:
                raise ValueError(
                    "which_fields_made_money requires either 'seasons' (explicit years) "
                    "or 'season_count_from_latest' (a relative window)"
                )
        return self


def resolve_relative_seasons(query: QueryObject, known_seasons: list[int]) -> list[int]:
    """Deterministically turn season_count_from_latest into a concrete season
    list, using the host's own known season range -- never the model's guess.
    Explicit `seasons` pass through unchanged.
    """
    if query.seasons:
        return query.seasons
    if query.season_count_from_latest:
        n = max(1, min(query.season_count_from_latest, len(known_seasons)))
        return sorted(known_seasons)[-n:]
    return list(known_seasons)
