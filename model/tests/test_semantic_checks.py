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
    "scale_total_bu": 17513.6,
    "monitor_total_bu": 17430.5,
    "pct_diff": -0.0047,
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
        "The yield monitor and scale ticket totals agree (17430.5 vs 17513.6 bu), but the "
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


# --- narrate_verified wiring: retry names the failure; audit gets failed_checks

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


def test_retry_names_the_failed_check_and_outcome_records_it(monkeypatch):
    from farm_model.narrator import narrate_verified

    good = (
        "Only 1 of 3 fields made money. Depot Forty had the highest profit at $17,549.90; "
        "Home Quarter lost $5,796.77."
    )
    prompts = _stub_narrations(monkeypatch, [EVAL5_WRONG, good])
    outcome = narrate_verified("Which fields made money in 2019 and 2020?", EVAL5_RANKING)
    assert outcome.text == good
    assert not outcome.used_fallback
    assert outcome.attempts_used == 2
    assert outcome.failed_checks == (("sign",),)
    assert "Specifically:" in prompts[1]
    assert "negative (loss) figure as a profit" in prompts[1]


def test_two_semantic_failures_fall_back_to_the_template(monkeypatch):
    from farm_model.narrator import narrate_verified

    _stub_narrations(monkeypatch, [EVAL11_WRONG, EVAL11_WRONG])
    outcome = narrate_verified(
        "Is any part of Section Corner losing money in 2024?", EVAL11_SECTION_CORNER
    )
    assert outcome.used_fallback
    assert outcome.failed_checks == (("zone_premise",), ("zone_premise",))


def test_prompt_states_the_reading_rules(monkeypatch):
    from farm_model.narrator import narrate_verified

    prompts = _stub_narrations(monkeypatch, ["East 80 had a bad year, not a bad field."])
    narrate_verified("Was East 80 a bad field or just a bad year?", EVAL2_EAST_80)
    assert "A negative profit is a loss" in prompts[0]
    assert 'Values under "modeled" are yield expectations in bu/ac' in prompts[0]
