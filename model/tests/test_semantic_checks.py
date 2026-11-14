"""Semantic narration checks (eval-fix P3). Model-free: each check is a pure
function over (narration, payload). Negative fixtures are the four narrations
from the eval run that passed the old grounding check while being wrong,
copied verbatim; positive fixtures are correct narrations of the same
payloads, so each check is shown not to over-reject.
"""

from __future__ import annotations

import pytest

from farm_model.verification import (
    check_attribution_not_causal,
    check_reconciliation_claim,
    check_sign_consistency,
    check_zone_premise,
    failed_semantic_checks,
)

# --- Payloads (shapes match the MCP tool results) -----------------------------

EVAL2_EAST_80 = {
    "canonical_id": "resolved_0002",
    "verdict": "bad_year",
    "evidence": {"outlier_seasons": [2020], "median_profit_per_acre": 68.18, "num_seasons": 10},
    "field_name": "East 80",
    "modeled": {
        "attribution": [
            {
                "season": 2020,
                "season_effect": -5.16,
                "field_effect": -7.75,
                "residual": -88.4,
                "calibrated": True,
                "units": "bu/ac of yield vs this field's own average yield (not dollars, not profit)",
            }
        ]
    },
}

EVAL5_RANKING = {
    "results": [
        {"display_name": "Depot Forty", "seasons": [2019, 2020], "total_profit": 17549.9},
        {"display_name": "Home Quarter", "seasons": [2019, 2020], "total_profit": -5796.77},
        {"display_name": "East 80", "seasons": [2019, 2020], "total_profit": -91297.48},
    ],
    "num_fields": 3,
    "num_fields_made_money": 1,
}

EVAL8_MARGINAL_2024 = {
    "field_name": "Marginal Eighty",
    "season": 2024,
    "scale_total_bu": 17430.5,
    "monitor_total_bu": 17513.6,
    "pct_diff": 0.0048,
    "totals_discrepancy": False,
    "coverage_gap_bins": 1,
    "coverage_gap_flagged": True,
    "note": "Yield monitor coverage has a gap despite totals reconciling normally.",
}

EVAL11_SECTION_CORNER = {
    "canonical_id": "resolved_0012",
    "season": 2024,
    "field_name": "Section Corner",
    "field_acres": 125.9,
    "field_profit": 5896.3,
    "zones": [
        {"zone_index": 0, "available": True, "profit": -11943.8},
        {"zone_index": 1, "available": True, "profit": 6100.0},
        {"zone_index": 2, "available": True, "profit": 5800.0},
        {"zone_index": 3, "available": True, "profit": 5940.1},
    ],
}

# --- Verbatim wrong narrations from the eval run (negative fixtures) ----------

EVAL2_WRONG = (
    "The field itself had a negative effect of -7.75, but the primary reason for the poor "
    "results was a particularly bad year with a seasonal effect of -5.16."
)
EVAL5_WRONG = (
    "Depot Forty made the most money in 2019 and 2020, while Home Quarter also had a profit "
    "of -$5796.77 during those years."
)
EVAL8_WRONG = (
    "The yield monitor data shows a slight difference in total bushels, 17430.5 versus "
    "17513.57. This indicates that a simple totals check wouldn't have identified this "
    "discrepancy."
)
EVAL11_WRONG = (
    "Based on the data, Section Corner is losing money in 2024. Zone 0 lost -11943.8, and "
    "this single zone's losses outweigh its gains."
)


def test_eval2_wrong_narration_fails_attribution():
    assert not check_attribution_not_causal(EVAL2_WRONG, EVAL2_EAST_80)
    assert failed_semantic_checks(EVAL2_WRONG, EVAL2_EAST_80) == ["attribution"]


def test_eval5_wrong_narration_fails_sign():
    assert not check_sign_consistency(EVAL5_WRONG, EVAL5_RANKING)
    assert failed_semantic_checks(EVAL5_WRONG, EVAL5_RANKING) == ["sign"]


def test_eval5_unsigned_magnitude_described_as_profit_also_fails():
    text = "Home Quarter had a profit of $5,796.77 over 2019 and 2020."
    assert not check_sign_consistency(text, EVAL5_RANKING)


def test_eval8_wrong_narration_fails_reconciliation():
    assert not check_reconciliation_claim(EVAL8_WRONG, EVAL8_MARGINAL_2024)
    assert failed_semantic_checks(EVAL8_WRONG, EVAL8_MARGINAL_2024) == ["reconciliation"]


def test_eval11_wrong_narration_fails_zone_premise():
    assert not check_zone_premise(EVAL11_WRONG, EVAL11_SECTION_CORNER)
    assert failed_semantic_checks(EVAL11_WRONG, EVAL11_SECTION_CORNER) == ["zone_premise"]


def test_eval11_losses_outweigh_alone_fails():
    text = "Zone 0 lost money and its losses outweigh the rest of the field."
    assert not check_zone_premise(text, EVAL11_SECTION_CORNER)


# --- Correct narrations (positive fixtures: no over-rejection) ----------------

@pytest.mark.parametrize(
    "text",
    [
        "East 80 had a bad year, not a bad field: the loss was confined to 2020, and its "
        "median profit was $68.18 per acre across 10 seasons.",
        "This was a bad year for East 80. Most of 2020's yield shortfall (-88.4 bu/ac) is "
        "not explained by the weather data, which fits a one-off event such as hail; the "
        "season effect of -5.16 bu/ac is the part the weather explains.",
        "East 80's loss was isolated to 2020. Its field effect of -7.75 bu/ac means it "
        "yields a little below the farm average every year.",
    ],
)
def test_correct_eval2_narrations_pass(text):
    assert failed_semantic_checks(text, EVAL2_EAST_80) == []


@pytest.mark.parametrize(
    "text",
    [
        "Only 1 of 3 fields made money in 2019 and 2020. Depot Forty had the highest profit "
        "at $17,549.90. Home Quarter lost $5,796.77 and East 80 lost $91,297.48.",
        "Depot Forty made a profit of $17,549.90, while Home Quarter had a loss of "
        "-$5,796.77.",
        "Depot Forty was the most profitable field ($17,549.90); East 80 was in the red at "
        "-$91,297.48.",
    ],
)
def test_correct_eval5_narrations_pass(text):
    assert failed_semantic_checks(text, EVAL5_RANKING) == []


@pytest.mark.parametrize(
    "text",
    [
        "The yield monitor and scale ticket totals agree (17513.6 vs 17430.5 bu), but the "
        "monitor missed part of the field: a coverage gap that a totals check alone would "
        "not catch.",
        "There's no discrepancy in the totals, yet the coverage check flagged a gap at one "
        "edge of Marginal Eighty in 2024.",
    ],
)
def test_correct_eval8_narrations_pass(text):
    assert failed_semantic_checks(text, EVAL8_MARGINAL_2024) == []


def test_reconciliation_check_does_not_apply_when_totals_really_disagree():
    payload = {**EVAL8_MARGINAL_2024, "totals_discrepancy": True}
    assert check_reconciliation_claim("The totals show a 6.9% discrepancy.", payload)


@pytest.mark.parametrize(
    "text",
    [
        "Zone 0 of Section Corner is losing money in 2024 (-11943.8), even though the field "
        "as a whole was profitable ($5896.3).",
        "Yes: 1 of 4 zones lost money. Section Corner is not losing money overall; it made "
        "$5896.3 in 2024.",
        "Section Corner made $5896.3 in 2024, but zone 0 lost money.",
    ],
)
def test_correct_eval11_narrations_pass(text):
    assert failed_semantic_checks(text, EVAL11_SECTION_CORNER) == []


def test_zone_premise_does_not_apply_when_field_really_lost_money():
    payload = {**EVAL11_SECTION_CORNER, "field_profit": -100.0}
    assert check_zone_premise("Section Corner is losing money this season.", payload)


def test_checks_ignore_payloads_they_dont_cover():
    plain = {"verdict": "bad_field", "evidence": {"loss_rate": 1.0, "num_seasons": 10}}
    assert failed_semantic_checks("Marginal Eighty lost money in all 10 seasons.", plain) == []


# --- narrate_verified wiring (template-first): the lead is the template; the
# model may add one sentence that must pass every check.

def _stub_narrations(monkeypatch, texts):
    import types

    from farm_model import narrator

    prompts = []
    replies = iter(texts)

    def fake_chat(model, messages, options):
        prompts.append(messages[0]["content"])
        return types.SimpleNamespace(message=types.SimpleNamespace(content=next(replies)))

    monkeypatch.setattr(narrator.ollama, "chat", fake_chat)
    return prompts


EVAL5_LEAD = "Fields that made money over 2019-2020: Depot Forty ($17,549.90)."


def test_lead_is_the_template_and_a_good_context_sentence_is_appended(monkeypatch):
    from farm_model.narrator import narrate_verified

    context = "Home Quarter and East 80 both lost money over the same two seasons."
    _stub_narrations(monkeypatch, [context])
    outcome = narrate_verified("Which fields made money in 2019 and 2020?", EVAL5_RANKING)
    assert outcome.lead == EVAL5_LEAD
    assert outcome.text == f"{EVAL5_LEAD} {context}"
    assert outcome.context == context
    assert not outcome.used_fallback
    assert outcome.failed_checks == ()


def test_retry_names_the_failed_check_and_records_the_rejected_text(monkeypatch):
    from farm_model.narrator import narrate_verified

    good = "Home Quarter lost $5,796.77 over the same seasons."
    prompts = _stub_narrations(monkeypatch, [EVAL5_WRONG, good])
    outcome = narrate_verified(
        "Which fields made money in 2019 and 2020?", EVAL5_RANKING, max_attempts=2
    )
    assert outcome.text == f"{EVAL5_LEAD} {good}"
    assert outcome.attempts_used == 2
    assert outcome.failed_checks == (("sign",),)
    # Only the first sentence of a reply is ever used.
    assert outcome.rejected_texts == (
        "Depot Forty made the most money in 2019 and 2020, while Home Quarter also had a "
        "profit of -$5796.77 during those years.",
    )
    assert "Specifically:" in prompts[1]
    assert "negative (loss) figure as a profit" in prompts[1]


def test_two_rejected_context_sentences_leave_the_template_alone(monkeypatch):
    from farm_model.narrator import narrate_verified

    _stub_narrations(monkeypatch, [EVAL11_WRONG, EVAL11_WRONG])
    outcome = narrate_verified(
        "Is any part of Section Corner losing money in 2024?", EVAL11_SECTION_CORNER,
        max_attempts=2,
    )
    assert outcome.used_fallback
    assert outcome.context is None
    assert outcome.text == (
        "Section Corner made $5,896.30 overall in 2024, but 1 of 4 measurable zones lost "
        "money: zone 0 (-$11,943.80)."
    )
    assert outcome.failed_checks == (("zone_premise",), ("zone_premise",))


def test_none_reply_means_no_context(monkeypatch):
    from farm_model.narrator import narrate_verified

    _stub_narrations(monkeypatch, ["NONE"])
    outcome = narrate_verified("Is there anything odd on Marginal Eighty in 2024?", EVAL8_MARGINAL_2024)
    assert outcome.context is None
    assert outcome.attempts_used == 1
    assert outcome.text.startswith("For Marginal Eighty in 2024, the yield monitor recorded 17,513.6 bu")


def test_prompt_shows_the_lead_and_the_reading_rules(monkeypatch):
    from farm_model.narrator import narrate_verified

    prompts = _stub_narrations(monkeypatch, ["NONE"])
    narrate_verified("Was East 80 a bad field or just a bad year?", EVAL2_EAST_80)
    assert "East 80 had a bad year, not a bad field" in prompts[0]
    assert "A negative profit is a loss" in prompts[0]
    assert "monitor_total_bu is the yield monitor" in prompts[0]


# --- Templates: correct by construction, and grounded -------------------------

EVAL9_COST = {
    "results": [
        {"field_name": "Sheyenne Bottom", "season": 2022, "line_item": "seed",
         "ledger_cost_per_ac": 95.55, "as_applied_derived_cost_per_ac": 59.61,
         "pct_diff": 0.6, "outlier_flagged": True, "note": "n"},
        {"field_name": "Sheyenne Bottom", "season": 2022, "line_item": "fertilizer",
         "ledger_cost_per_ac": 120.1, "as_applied_derived_cost_per_ac": 119.8,
         "pct_diff": 0.0025, "outlier_flagged": False, "note": "n"},
    ]
}


@pytest.mark.parametrize(
    "payload,question,expected",
    [
        (EVAL2_EAST_80, "Was East 80 a bad field or just a bad year?",
         "East 80 had a bad year, not a bad field: 2020 was a clear outlier, and its median "
         "profit across 10 recorded seasons was $68.18/ac."),
        (EVAL8_MARGINAL_2024, "Anything odd about Marginal Eighty in 2024?",
         "For Marginal Eighty in 2024, the yield monitor recorded 17,513.6 bu and the scale "
         "tickets 17,430.5 bu: the totals agree within tolerance. But the yield monitor's "
         "coverage has a gap -- part of the field wasn't recorded, which a totals-only check "
         "would miss."),
        (EVAL9_COST, "Does the seed cost on Sheyenne Bottom in 2022 look right?",
         "For Sheyenne Bottom in 2022, this doesn't look right: seed (ledger $95.55/ac vs $59.61/ac "
         "from the as-applied records)."),
        ({"canonical_boundary_name": "N 80", "method": "alias"},
         'What does "north eighty" refer to in 2017?',
         "That name refers to the field N 80 (a recorded alias)."),
    ],
)
def test_templates_are_exact_and_grounded(payload, question, expected):
    from farm_model.narrator import template_answer
    from farm_model.verification import check_narration_grounded

    text = template_answer(question, payload)
    assert text == expected
    assert check_narration_grounded(text, payload, question=question).is_grounded
    assert failed_semantic_checks(text, payload) == []


# --- Unsupported cause (P3c) ---------------------------------------------------
# Verbatim model sentence from the live P3b rerun (runs 1 and 3 of eval 2):
# no payload field mentions weather, so the cause is invented.
EVAL2_INVENTED_CAUSE = (
    "The data shows East 80's profit was significantly lower than its historical "
    "average due to unusual weather conditions in 2020."
)
# The real payload carries the report-export glossary labels, which mention
# weather and "e.g. hail, pests, management" -- vocabulary, not evidence.
EVAL2_EAST_80_LABELLED = {
    **EVAL2_EAST_80,
    "modeled": {
        "attribution": [
            {
                **EVAL2_EAST_80["modeled"]["attribution"][0],
                "meaning": {
                    "season_effect": "yield change this season's recorded weather explains",
                    "residual": "yield shortfall the weather data does not explain "
                    "(e.g. hail, pests, management)",
                },
            }
        ]
    },
}
EVAL2_PLAIN_CONTEXT = (
    "The data shows East 80's profit was significantly lower than its typical "
    "performance over ten seasons."
)


def test_unsupported_cause_rejects_invented_weather():
    from farm_model.verification import check_no_unsupported_cause

    assert not check_no_unsupported_cause(EVAL2_INVENTED_CAUSE, EVAL2_EAST_80)
    assert not check_no_unsupported_cause(EVAL2_INVENTED_CAUSE, EVAL2_EAST_80_LABELLED)
    assert not check_no_unsupported_cause(
        "The 2020 loss was caused by hail.", EVAL2_EAST_80_LABELLED
    )
    assert "unsupported_cause" in failed_semantic_checks(EVAL2_INVENTED_CAUSE, EVAL2_EAST_80)


def test_unsupported_cause_passes_plain_context():
    from farm_model.verification import check_no_unsupported_cause

    assert check_no_unsupported_cause(EVAL2_PLAIN_CONTEXT, EVAL2_EAST_80_LABELLED)
    # Describing what the weather data does or doesn't explain is not a causal claim.
    assert check_no_unsupported_cause(
        "Most of the 2020 shortfall is not explained by the weather data.",
        EVAL2_EAST_80_LABELLED,
    )


def test_unsupported_cause_allows_cause_named_in_payload():
    from farm_model.verification import check_no_unsupported_cause

    payload = {**EVAL2_EAST_80, "notes": "Hail on 2020-07-14 across the north half."}
    assert check_no_unsupported_cause("The 2020 loss was caused by hail in July.", payload)
    assert not check_no_unsupported_cause("The 2020 loss was due to drought.", payload)


# Found in the grower web app: the cause list held "planting" but not
# "planted", so this sentence passed every check.
PLANTED_TOO_LATE = "East 80 lost money in 2020 because the farmer planted too late."


def test_unsupported_cause_catches_verb_and_plural_forms():
    from farm_model.verification import check_no_unsupported_cause

    for sentence in (
        PLANTED_TOO_LATE,
        "The 2020 loss happened because the field flooded in June.",
        "Profit fell in 2020 because it rained too much at harvest.",
        "The shortfall was driven by storms in July.",
        "Yield dropped because the crop froze in May.",
        "The loss was due to the field being mismanaged.",
    ):
        assert not check_no_unsupported_cause(sentence, EVAL2_EAST_80_LABELLED), sentence
    assert "unsupported_cause" in failed_semantic_checks(PLANTED_TOO_LATE, EVAL2_EAST_80)


def test_unsupported_cause_word_forms_supported_by_payload():
    from farm_model.verification import check_no_unsupported_cause

    payload = {**EVAL2_EAST_80, "notes": "Replanted 2020-06-02 after the first stand failed."}
    assert check_no_unsupported_cause(PLANTED_TOO_LATE, payload)
    # A cause word that's only a non-causal mention still passes.
    assert check_no_unsupported_cause(
        "East 80 was planted in every recorded season.", EVAL2_EAST_80_LABELLED
    )


def test_unsupported_cause_retry_reason_exists():
    from farm_model import narrator

    assert "unsupported_cause" in narrator._RETRY_REASONS
