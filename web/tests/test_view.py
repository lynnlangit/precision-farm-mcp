"""Model-free tests for the grower web app's panels: no Ollama, no MCP
servers, no browser. Payloads mirror real tool results (seed 42)."""

from __future__ import annotations

from farm_host.cli import AnswerResult
from farm_model.narrator import NarrationOutcome
from farm_model.query_schema import QueryIntent, QueryObject
from farm_model.verification import SEMANTIC_CHECKS, GroundingResult

from farm_web.view import CHECKS, build_view, empty_view, format_value

EAST_80 = {
    "canonical_id": "resolved_0002",
    "verdict": "bad_year",
    "evidence": {
        "outlier_seasons": [2020],
        "median_profit_per_acre": 68.19,
        "num_seasons": 10,
        "num_loss_seasons": 3,
    },
    "field_name": "East 80",
    "provenance": {
        "data_dir": "/x",
        "built_at": "2026-11-13T02:06:43+00:00",
        "source_file_count": 137,
    },
    "modeled": {
        "attribution": [
            {
                "season": 2020,
                "season_effect": -5.16,
                "field_effect": -7.75,
                "residual": -89.09,
                "calibrated": True,
                "units": "bu/ac of yield vs this field's own average yield",
                "meaning": {"residual": "e.g. hail, pests"},
            }
        ]
    },
}

COST = {
    "results": [
        {"field_name": "Riverside", "season": 2022, "line_item": "seed",
         "ledger_cost_per_ac": 95.55, "as_applied_derived_cost_per_ac": 60.04,
         "pct_diff": -0.3716, "outlier_flagged": True, "note": "Seed differs by -37.2%."},
        {"field_name": "Riverside", "season": 2022, "line_item": "fertilizer",
         "ledger_cost_per_ac": 134.31, "as_applied_derived_cost_per_ac": 128.62,
         "pct_diff": -0.0424, "outlier_flagged": False, "note": "Fertilizer reconciles."},
    ],
    "provenance": {"source_file_count": 137},
    "modeled": None,
}


def _outcome(context=None, failed=(), rejected=()) -> NarrationOutcome:
    lead = "East 80 had a bad year, not a bad field."
    return NarrationOutcome(
        text=f"{lead} {context}" if context else lead,
        truncated=False,
        measured_or_derived_grounding=GroundingResult([]),
        modeled_grounding=None,
        attempts_used=1 + len(rejected),
        used_fallback=context is None,
        failed_checks=tuple(failed),
        rejected_texts=tuple(rejected),
        lead=lead,
        context=context,
    )


def _result(payload=EAST_80, narration=None, **kw) -> AnswerResult:
    return AnswerResult(
        text="unused",
        ok=True,
        query=QueryObject(intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR, field_name="East 80"),
        server="report-export",
        tool="bad_field_or_bad_year",
        tool_args={"field_name": "East 80"},
        payload=payload,
        narration=narration or _outcome(),
        therefore="Therefore: the loss was isolated to 2020.",
        **kw,
    )


def test_every_narrator_check_has_a_plain_label():
    # A new check added to the verifier must get a grower-facing label here.
    names = {name for name, _ in CHECKS}
    assert set(SEMANTIC_CHECKS) <= names
    assert {"ungrounded", "verdict"} <= names


def test_shown_sentence_lists_all_checks_as_passed():
    view = build_view(_result(narration=_outcome(context="The weather explains part of it.")))
    assert "Added by the AI, then checked" in view.answer_html
    assert f"passed all {len(CHECKS)} checks" in view.checks_html
    assert view.checks_html.count('class="pass"') == len(CHECKS)


def test_rejected_sentence_is_shown_struck_with_failed_check():
    view = build_view(
        _result(
            narration=_outcome(
                failed=[("unsupported_cause",)], rejected=["It lost money because of hail."]
            )
        )
    )
    assert "Added by the AI" not in view.answer_html  # never shown as part of the answer
    assert "failed a check" in view.checks_html
    assert "It lost money because of hail." in view.checks_html
    assert "name a cause your records don" in view.checks_html


def test_therefore_line_is_sentence_cased_without_prefix():
    view = build_view(_result())
    assert "Therefore:" not in view.answer_html
    assert "The loss was isolated to 2020." in view.answer_html


def test_figures_show_evidence_and_label_modeled_estimate():
    view = build_view(_result())
    assert "Bad year (a one-season outlier)" in view.figures_html
    assert "$68.19" in view.figures_html
    assert "Modeled estimate, not a measurement" in view.figures_html
    assert "resolved_0002" not in view.figures_html  # internal ids stay hidden


def test_cost_table_drops_repeated_context_and_flags_outlier():
    view = build_view(_result(payload=COST))
    assert "Riverside" not in view.figures_html.split("</table>")[0]  # repeated column dropped
    assert "-37.2%" in view.figures_html
    assert '<td class="flag">Yes</td>' in view.figures_html
    assert 'class="pf-note pf-note-ok">Fertilizer reconciles.' in view.figures_html


def test_untrusted_text_is_escaped():
    payload = dict(EAST_80, field_name="<script>alert(1)</script>")
    view = build_view(
        _result(payload=payload, narration=_outcome(context="<img src=x onerror=alert(1)>"))
    )
    for html in (view.answer_html, view.figures_html):
        assert "<script>" not in html and "<img" not in html


def test_refusals_explain_without_inventing_checks():
    view = build_view(
        AnswerResult(
            text="Couldn't reach the local model.", ok=False, refusal_kind="model_unreachable"
        )
    )
    assert "local AI model isn&#x27;t running" in view.answer_html
    assert "nothing to check" in view.checks_html


def test_format_value():
    assert format_value("total_profit", -112044.66) == "-$112,044.66"
    assert format_value("pct_diff", 0.0693) == "+6.9%"
    assert format_value("loss_rate", 1.0) == "100%"
    assert format_value("season", 2020) == "2020"
    assert format_value("totals_discrepancy", True) == "Yes"
    assert format_value("x", None) == "&mdash;"


def test_empty_view_invites_a_question():
    assert "tap an example question" in empty_view().answer_html
