"""The narrator withholds a model sentence that fails a check, and samples
with a fixed seed so a demo shows what the evals saw. Model-free: ollama.chat
is replaced by a stand-in that returns fixed text, so this runs anywhere.
The real-model version is host/tests/test_eval_nl.py -k withheld."""

from __future__ import annotations

import types

import farm_model.narrator as narrator
from farm_model.narrator import NARRATION_SEED, narrate_verified

# Eval 16's payload (report-export.bad_field_or_bad_year, East 80, seed 42).
EAST_80 = {
    "verdict": "bad_year",
    "evidence": {"outlier_seasons": [2020], "median_profit_per_acre": 68.19,
                 "num_seasons": 10, "num_loss_seasons": 3},
    "field_name": "East 80",
    "modeled": {"attribution": [{
        "season": 2020, "season_effect": -5.16, "field_effect": -7.75, "residual": -89.09,
        "calibrated": True,
        "units": "bu/ac of yield vs this field's own average yield (not dollars, not profit)",
        "meaning": {"residual": "yield shortfall the weather data does not explain "
                                "(e.g. hail, pests, management)"},
    }]},
}
QUESTION = "What caused East 80's bad year?"


def _fake_chat(replies: list[str], seen: list[dict]):
    def chat(model, messages, options=None, **kw):
        seen.append(options or {})
        return types.SimpleNamespace(message=types.SimpleNamespace(content=replies.pop(0)))
    return chat


def test_a_cause_the_records_dont_hold_is_withheld_on_every_try(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(narrator.ollama, "chat", _fake_chat([
        "The 2020 loss was most likely due to hail damage.",
        "It was caused by weather, pests or management in 2020.",
    ], seen))
    out = narrate_verified(QUESTION, EAST_80)
    assert out.context is None and out.used_fallback
    assert out.text == out.lead  # the verified answer stands alone
    assert len(out.rejected_texts) == 2
    assert all("unsupported_cause" in failed for failed in out.failed_checks)
    # Both tries sampled with the fixed seed.
    assert [o.get("seed") for o in seen] == [NARRATION_SEED, NARRATION_SEED]


def test_a_passing_retry_is_shown(monkeypatch):
    monkeypatch.setattr(narrator.ollama, "chat", _fake_chat([
        "The 2020 loss was most likely due to hail damage.",
        "Weather explains only 5.16 bu/ac of the 2020 shortfall.",
    ], []))
    out = narrate_verified(QUESTION, EAST_80)
    assert out.context == "Weather explains only 5.16 bu/ac of the 2020 shortfall."
    assert out.failed_checks == (("unsupported_cause",),)
