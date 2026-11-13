"""One deterministic, template-built sentence appended after an answer --
never model-generated, so it can never invent a claim the payload doesn't
support. Strictly a restatement of what was actually computed, not advice:
v1 is retrospective arithmetic only (see README.md), so a "therefore" that
suggested what to do about a result would overstep that boundary the same
way a prediction or recommendation would. Omitted entirely, not guessed at,
whenever a payload doesn't carry a claim worth restating (no_data verdicts,
reconciliation lookups, resolve_field_name) -- see build_therefore_line's
docstring for the full list of what's covered and what's deliberately not.
"""

from __future__ import annotations


def _for_verdict(payload: dict) -> str | None:
    verdict = payload.get("verdict")
    evidence = payload.get("evidence", {})
    if verdict == "bad_field":
        return (
            f"Therefore: this field lost money in {evidence.get('loss_rate', 0) * 100:.0f}% "
            f"of its {evidence.get('num_seasons', '?')} recorded seasons -- a repeating "
            "pattern, not a single bad year."
        )
    if verdict == "bad_year":
        seasons = evidence.get("outlier_seasons", [])
        return (
            f"Therefore: the loss was isolated to {', '.join(str(s) for s in seasons)} -- "
            "every other recorded season was unremarkable, not a sign of a chronic problem."
        )
    if verdict == "consistently_profitable":
        num_seasons = evidence.get("num_seasons")
        losses = evidence.get("num_loss_seasons")
        median = evidence.get("median_profit_per_acre")
        median_txt = f" (median ${median:,.2f}/ac)" if median is not None else ""
        if losses is None or num_seasons is None:
            # Older payload without the integer count -- don't derive it from
            # the rounded loss_rate, and don't claim zero losses either.
            return (
                f"Therefore: this field's record{median_txt} shows neither a chronic loss "
                "pattern nor a single standout bad year."
            )
        if losses == 0:
            return (
                f"Therefore: this field lost money in none of its {num_seasons} recorded "
                f"seasons{median_txt}."
            )
        return (
            f"Therefore: this field lost money in {losses} of {num_seasons} recorded "
            f"seasons{median_txt} -- neither a chronic pattern nor a single standout bad year."
        )
    return None  # "no_data" -- nothing was computed, so nothing to restate


def _for_zone_profitability(payload: dict) -> str | None:
    zones = payload.get("zones", [])
    available = [z for z in zones if z.get("available")]
    if not available:
        return None  # every zone lacked coverage -- no honest claim to make
    unprofitable = [z for z in available if (z.get("profit") or 0) < 0]
    field_profit = payload.get("field_profit", 0)
    if field_profit <= 0:
        return "Therefore: this field lost money overall this season, not just in part."
    if unprofitable:
        return (
            f"Therefore: {len(unprofitable)} of {len(available)} measurable zones lost "
            "money this season even though the field as a whole was profitable."
        )
    return "Therefore: no measurable zone in this field lost money on its own this season."


def _for_unprofitable_zones_summary(payload: dict) -> str | None:
    pct = payload.get("pct_acres_unprofitable_in_profitable_fields")
    if pct is None:
        return None  # no as-applied-covered, profitable field-seasons to examine
    return (
        f"Therefore: {pct * 100:.1f}% of acres in otherwise-profitable fields sat in a "
        "zone that lost money, across the seasons examined."
    )


def _money(value: float) -> str:
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def _season_span(results: list[dict]) -> str:
    seasons = sorted({s for r in results for s in r.get("seasons", [])})
    if not seasons:
        return "the seasons examined"
    if len(seasons) == 1:
        return str(seasons[0])
    if seasons == list(range(seasons[0], seasons[-1] + 1)):
        return f"{seasons[0]}-{seasons[-1]}"
    return ", ".join(str(s) for s in seasons[:-1]) + f" and {seasons[-1]}"


def _for_ranking(payload: dict) -> str | None:
    results = payload.get("results", [])
    if not results:
        return None
    top, bottom = results[0], results[-1]
    total = payload.get("num_fields", len(results))
    made_money = payload.get(
        "num_fields_made_money", sum(1 for r in results if r.get("total_profit", 0) > 0)
    )
    line = (
        f"Therefore: {made_money} of {total} fields made money over {_season_span(results)}; "
        f"{top.get('display_name', 'the top field')} ranked highest "
        f"({_money(top.get('total_profit', 0))})"
    )
    if len(results) > 1:
        line += (
            f", {bottom.get('display_name', 'the bottom field')} lowest "
            f"({_money(bottom.get('total_profit', 0))})"
        )
    return line + "."


def build_therefore_line(payload: dict) -> str | None:
    """Returns one deterministic sentence, or None if this payload shape
    doesn't carry a claim worth restating. Checked in this order because a
    payload can carry more than one of these keys incidentally (e.g. a
    zone_profitability payload has no "verdict", so order only matters for
    payloads this router hasn't seen yet -- keep the most specific check
    first if a future result type could match more than one branch):

    - {"verdict": ...} (bad_field_or_bad_year / explain_shortfall)
    - {"zones": [...], "field_profit": ...} (zone_profitability)
    - {"pct_acres_unprofitable_in_profitable_fields": ...} (the farm-wide summary)
    - {"results": [...]} (which_fields_made_money)

    Deliberately NOT covered -- resolve_field_name, yield_reconciliation,
    cost_reconciliation: these are lookups/comparisons with no single
    verdict to restate, and reaching for one would mean inventing a claim
    the computation didn't actually make.
    """
    if "verdict" in payload:
        return _for_verdict(payload)
    if "zones" in payload and "field_profit" in payload:
        return _for_zone_profitability(payload)
    if "pct_acres_unprofitable_in_profitable_fields" in payload:
        return _for_unprofitable_zones_summary(payload)
    results = payload.get("results")
    # Only which_fields_made_money rows carry total_profit. cost_reconciliation
    # also returns {"results": [...]} (line items) and must get no line --
    # before this check it printed "0 of 2 fields made money ... ($0.00)".
    if isinstance(results, list) and results and all(
        isinstance(r, dict) and "total_profit" in r for r in results
    ):
        return _for_ranking(payload)
    return None
