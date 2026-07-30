"""Renders docs/EVAL_QUESTIONS.md -- generated fresh each run from
ground_truth.json's own data so the doc can never drift from the actual
synthetic answer key, same shape and call site as readme.py's
render_readme.

Questions 1-3 and 4-5 mirror farm_core.profitability's classification and
ranking logic (loss-rate / MAD-outlier rule, total-profit-over-a-season-
window ranking) reimplemented locally, kept in sync by hand -- the
generator package has no dependency on farm_core, same rationale as
generator/tests/test_qualitative_fixtures.py. Questions 7 and 9 are phrased
directly off the generator's own raw defect numbers (monitor vs. scale-
ticket totals; ledger vs. correct seed cost) rather than farm_core's
independently-recomputed reconciliation estimate, which this package can't
reproduce without duplicating cross-source reconciliation logic that
legitimately belongs only in farm_core.
"""

from __future__ import annotations

import statistics

LOSS_RATE_BAD_FIELD_THRESHOLD = 0.5
OUTLIER_MAD_MULTIPLIER = 2.0


def _classify(profits_by_season: dict[str, float]) -> tuple[str, dict]:
    profits = list(profits_by_season.values())
    loss_rate = sum(1 for p in profits if p < 0) / len(profits)
    if loss_rate >= LOSS_RATE_BAD_FIELD_THRESHOLD:
        return "bad_field", {"loss_rate": round(loss_rate, 2)}

    median_profit = statistics.median(profits)
    mad = statistics.median(abs(p - median_profit) for p in profits)
    outliers = []
    if mad > 0:
        outliers = [
            int(s)
            for s, p in profits_by_season.items()
            if (median_profit - p) / mad > OUTLIER_MAD_MULTIPLIER
        ]
    if outliers:
        return "bad_year", {"outlier_seasons": outliers, "median_profit_per_acre": median_profit}
    return "consistently_profitable", {"loss_rate": round(loss_rate, 2), "median_profit_per_acre": median_profit}


def _current_name(ground_truth: dict, field_id: str) -> str:
    field = ground_truth["canonical_fields"][field_id]
    seasons = sorted(field["display_name_by_season"], key=int)
    return field["display_name_by_season"][seasons[-1]]


def _profits_by_season(ground_truth: dict, field_id: str) -> dict[str, float]:
    return {s: v["profit_per_acre"] for s, v in ground_truth["profitability"][field_id].items()}


def _which_fields_made_money(ground_truth: dict, seasons: list[int]) -> list[dict]:
    season_set = {str(s) for s in seasons}
    results = []
    for field_id, by_season in ground_truth["profitability"].items():
        recs = [(s, v) for s, v in by_season.items() if s in season_set]
        if not recs:
            continue
        results.append(
            {
                "field_id": field_id,
                "display_name": _current_name(ground_truth, field_id),
                "total_profit": round(sum(v["profit"] for _, v in recs), 2),
            }
        )
    results.sort(key=lambda r: r["total_profit"], reverse=True)
    return results


def _find_negative_control(ground_truth: dict, exclude: set[str]) -> tuple[str, dict]:
    """A field with neither a bad_field nor a bad_year story -- the negative
    control for Q3. Picked dynamically (not a hardcoded field name) because
    which specific field qualifies can shift across regenerations as the
    causal yield model's constants are tuned.
    """
    candidates = []
    for field_id in ground_truth["profitability"]:
        if field_id in exclude:
            continue
        profits = _profits_by_season(ground_truth, field_id)
        verdict, evidence = _classify(profits)
        if verdict == "consistently_profitable":
            candidates.append((field_id, len(profits), evidence))
    if not candidates:
        raise AssertionError("no consistently_profitable field found for Q3's negative control")
    # Longest season history first -- a more convincing "normal, unremarkable
    # field" story than a short-lived split/merge child with few data points.
    candidates.sort(key=lambda c: (-c[1], c[2]["loss_rate"], c[0]))
    field_id, _num_seasons, evidence = candidates[0]
    return field_id, evidence


def render_eval_questions(ground_truth: dict) -> str:
    seasons = ground_truth["generator"]["seasons"]
    marginal_id = ground_truth["marginal_field_id"]
    cat = ground_truth["catastrophic_year"]
    ws = ground_truth["weathershortfall"]
    ms = ground_truth["mgmtshortfall"]

    marginal_verdict, marginal_evidence = _classify(_profits_by_season(ground_truth, marginal_id))
    cat_verdict, cat_evidence = _classify(_profits_by_season(ground_truth, cat["field_id"]))

    control_id, control_evidence = _find_negative_control(
        ground_truth, exclude={marginal_id, cat["field_id"], ws["field_id"], ms["field_id"]}
    )

    last_five = seasons[-5:]
    top5 = _which_fields_made_money(ground_truth, last_five)
    named_years = [seasons[min(3, len(seasons) - 1)], seasons[min(4, len(seasons) - 1)]]
    top_named = _which_fields_made_money(ground_truth, named_years)

    drift_defect = next(d for d in ground_truth["defects"] if d["type"] == "naming_drift")
    drift_field_id = drift_defect["field_id"]
    canonical_name = drift_defect["canonical_name"]
    variants_by_season = drift_defect["variants_by_season"]
    # Pick a season whose ledger spelling actually differs from the canonical
    # name -- a lower-cased copy of the same string would be a weak example
    # of "resolves through drift."
    drift_season, drift_variant = next(
        (s, v) for s, v in sorted(variants_by_season.items(), key=lambda kv: int(kv[0]))
        if v != canonical_name
    )

    cal_defects = sorted(
        (d for d in ground_truth["defects"] if d["type"] == "yield_monitor_calibration_error"),
        key=lambda d: d["defect_id"],
    )
    cal = cal_defects[0]
    cal_name = ground_truth["canonical_fields"][cal["field_id"]]["display_name_by_season"][
        str(cal["season"])
    ]

    swath_defects = [d for d in ground_truth["defects"] if d["type"] == "missing_swath"]
    swath = swath_defects[0]
    swath_name = ground_truth["canonical_fields"][swath["field_id"]]["display_name_by_season"][
        str(swath["season"])
    ]

    digit_defects = [d for d in ground_truth["defects"] if d["type"] == "transposed_digit"]
    digit = digit_defects[0]
    digit_name = ground_truth["canonical_fields"][digit["field_id"]]["display_name_by_season"][
        str(digit["season"])
    ]

    rental_lost_event = next(
        e for e in ground_truth["identity_events"] if e["type"] == "rental_lost"
    )
    rental_lost_id = rental_lost_event["field_id"]
    rental_lost_name = ground_truth["canonical_fields"][rental_lost_id]["display_name_by_season"][
        sorted(ground_truth["canonical_fields"][rental_lost_id]["display_name_by_season"], key=int)[
            -1
        ]
    ]

    lines = [
        "# Precision Farm MCP v1 -- Evaluation Questions",
        "",
        "Independent, read-only questions for the CLI, in the style of the "
        "precision-medicine-mcp evals: each requires at least one real MCP tool call "
        "(several route through reconciliation across two independent sources), and "
        "each has a single answer that's verifiable directly against "
        f"`data/synthetic/ground_truth.json` (seed {ground_truth['generator']['seed']}). No "
        "question depends on the answer to another. Generated fresh from "
        "`ground_truth.json` on every `generator` run -- never hand-edited.",
        "",
        "Run any of them with:",
        "",
        "```bash",
        'uv run --project host farm-cli "<question>"',
        "```",
        "",
        "---",
        "",
        "### 1. Chronic loss pattern",
        f"**Q:** Was the {_current_name(ground_truth, marginal_id)} a bad field or just a "
        "bad year?",
        f"**Tool:** `report-export.bad_field_or_bad_year(field_name="
        f'"{_current_name(ground_truth, marginal_id)}")`',
        f"**Verifiable answer:** `verdict = {marginal_verdict!r}`, loss in "
        f"`{sum(1 for p in _profits_by_season(ground_truth, marginal_id).values() if p < 0)}/"
        f"{len(_profits_by_season(ground_truth, marginal_id))}` recorded seasons "
        f"(`loss_rate = {marginal_evidence['loss_rate']}`). Ground truth: `marginal_field_id` "
        "field, most seasons in `profitability.<field>.*.profit < 0`.",
        "",
        "### 2. A genuine one-season outlier",
        f"**Q:** Was {_current_name(ground_truth, cat['field_id'])} a bad field or just a "
        "bad year?",
        f"**Tool:** `report-export.bad_field_or_bad_year(field_name="
        f'"{_current_name(ground_truth, cat["field_id"])}")`',
        f"**Verifiable answer:** `verdict = {cat_verdict!r}`, outlier season is exactly "
        f"`{cat_evidence['outlier_seasons']}`, median profit/acre "
        f"`${cat_evidence['median_profit_per_acre']:,.2f}`. Ground truth: `catastrophic_year` "
        f"= `{cat}`.",
        "",
        "### 3. A normal, unremarkable field",
        f"**Q:** Was {_current_name(ground_truth, control_id)} a bad field or just a bad "
        "year?",
        f"**Tool:** `report-export.bad_field_or_bad_year(field_name="
        f'"{_current_name(ground_truth, control_id)}")`',
        f"**Verifiable answer:** `verdict = {'consistently_profitable'!r}`, loss in only "
        f"`{sum(1 for p in _profits_by_season(ground_truth, control_id).values() if p < 0)}/"
        f"{len(_profits_by_season(ground_truth, control_id))}` seasons, median profit/acre "
        f"`${control_evidence['median_profit_per_acre']:,.2f}`. Included as the negative "
        "control: most fields in the record are neither pattern.",
        "",
        "### 4. Ranking over a relative window",
        f"**Q:** Which fields made money in the last five years?",
        f"**Tool:** `report-export.which_fields_made_money(seasons=[{last_five[0]}.."
        f"{last_five[-1]}])`",
        f"**Verifiable answer:** Top result is **{top5[0]['display_name']}**, total profit "
        f"`${top5[0]['total_profit']:,.2f}`; {top5[-1]['display_name']} is last, total profit "
        f"`${top5[-1]['total_profit']:,.2f}`. The five-year window must resolve to "
        f"`{last_five}` -- the five most recent known seasons, not any other five.",
        "",
        "### 5. Ranking over explicit named years",
        f"**Q:** Which fields made money in {named_years[0]} and {named_years[1]}?",
        f"**Tool:** `report-export.which_fields_made_money(seasons={named_years})`",
        f"**Verifiable answer:** Top result is **{top_named[0]['display_name']}**, total "
        f"profit `${top_named[0]['total_profit']:,.2f}`. Named years must resolve to exactly "
        f"`{named_years}`, not a relative-count guess.",
        "",
        "### 6. Naming-drift resolution",
        f'**Q:** What does "{drift_variant}" refer to in {drift_season}?',
        f'**Tool:** `field-registry.resolve_field_name(raw_name="{drift_variant}", '
        f"season={drift_season})`",
        f'**Verifiable answer:** Resolves to canonical boundary name **"{canonical_name}"** '
        f"via `method = \"alias\"`. Ground truth: `DEF-NAMEDRIFT-{drift_field_id}`, one of the "
        "spelling variants cycling by season.",
        "",
        "### 7. A genuine yield-monitor discrepancy",
        f"**Q:** Do the yield monitor and scale tickets agree on {cal_name} in "
        f"{cal['season']}?",
        f'**Tool:** `yield-history.get_yield_reconciliation(field_name="{cal_name}", '
        f"season={cal['season']})`",
        f"**Verifiable answer:** `totals_discrepancy = true`, `pct_diff ~= "
        f"{cal['pct_diff']}%` (monitor total {cal['monitor_total_bu']:,.0f} bu vs. scale "
        f"ticket total {cal['scale_ticket_total_bu']:,.0f} bu). Ground truth: "
        f"`{cal['defect_id']}`.",
        "",
        "### 8. A coverage gap that totals alone would miss",
        f"**Q:** Is there anything odd about the yield monitor coverage on {swath_name} in "
        f"{swath['season']}?",
        f'**Tool:** `yield-history.get_yield_reconciliation(field_name="{swath_name}", '
        f"season={swath['season']})`",
        f"**Verifiable answer:** `coverage_gap_flagged = true` **and** "
        f"`totals_discrepancy = false` -- the defining property of this defect "
        f"(`{swath['defect_id']}`) is that a totals-only check would miss it entirely; only "
        "the spatial coverage check catches it.",
        "",
        "### 9. A ledger entry that doesn't match its own inputs",
        f"**Q:** Does the seed cost on {digit_name} in {digit['season']} look right?",
        f'**Tool:** `cost-ledger.get_cost_reconciliation(field_name="{digit_name}", '
        f"season={digit['season']})`",
        f"**Verifiable answer:** The `\"seed\"` line item is `outlier_flagged = true` -- the "
        f"ledger records `${digit['ledger_value']:,.2f}/ac` where the correct figure is "
        f"`${digit['correct_value']:,.2f}/ac` (a single transposed digit). Ground truth: "
        f"`{digit['defect_id']}`.",
        "",
        "### 10. A field that no longer exists",
        f'**Q:** What does "{rental_lost_name}" refer to in {rental_lost_event["effective_season"] + 1}?',
        f'**Tool:** `field-registry.resolve_field_name(raw_name="{rental_lost_name}", '
        f"season={rental_lost_event['effective_season'] + 1})`",
        "**Verifiable answer:** A structured refusal -- "
        '`{"code": "not_found"}` -- never a guess. Ground truth: '
        f"`{rental_lost_event['event_id']}`, lease ended after season "
        f"{rental_lost_event['effective_season']}; no boundary exists for this field from "
        f"{rental_lost_event['effective_season'] + 1} onward.",
        "",
        "---",
        "",
        "## What these are testing collectively",
        "",
        "- **1-3** exercise the classifier's two failure-mode-vs-normal-case split -- "
        "chronic pattern, one-off outlier, and neither.",
        "- **4-5** exercise the deterministic relative-vs-explicit season resolution -- the "
        "model extracts a count or explicit years; a plain Python function resolves either "
        "into concrete seasons, never the model's own arithmetic.",
        "- **6, 10** exercise field-identity resolution at its two extremes: a name that "
        "resolves through drift, and a name that correctly resolves to nothing at all.",
        "- **7-9** exercise all three reconciliation defects Phase 2 was built to catch, "
        "including the one (#8) specifically designed so a naive totals-only check would "
        "pass it silently.",
        "",
    ]

    return "\n".join(lines) + "\n"
