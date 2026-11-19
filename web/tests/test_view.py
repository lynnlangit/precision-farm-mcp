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
        {"field_name": "Sheyenne Bottom", "season": 2022, "line_item": "seed",
         "ledger_cost_per_ac": 95.55, "as_applied_derived_cost_per_ac": 60.04,
         "pct_diff": -0.3716, "outlier_flagged": True, "note": "Seed differs by -37.2%."},
        {"field_name": "Sheyenne Bottom", "season": 2022, "line_item": "fertilizer",
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


def test_withheld_sentence_is_flagged_in_the_answer_and_its_failed_check_is_open():
    view = build_view(
        _result(
            narration=_outcome(
                failed=[("unsupported_cause",), ("unsupported_cause", "verdict")],
                rejected=["It lost money because of hail.", "Weather caused it."],
            )
        )
    )
    # The answer card says a sentence was withheld; the last try is shown
    # only inside a folded "See what it wrote", never as part of the answer.
    assert "Added by the AI" not in view.answer_html
    assert "AI sentence withheld" in view.answer_html
    assert '<details class="pf-line pf-line-withheld">' in view.answer_html  # folded
    assert "See what it wrote" in view.answer_html
    assert "Weather caused it." in view.answer_html.split("<blockquote>")[1]
    assert "hail" not in view.answer_html  # only the last try
    assert "agrees with the verified answer" in view.answer_html  # why it was stopped
    # Its panel opens by itself, with the failed count on its folded line.
    assert view.checks_open is True
    assert view.checks_summary == "2 of 9 failed \u00b7 AI sentence withheld"
    assert view.checks_tone == "warn"
    # The checks panel shows both tries, open, each with the full checklist.
    assert "withheld: it failed a check on all 2 tries" in view.checks_html
    assert view.checks_html.count('<details class="pf-rejected" open>') == 2
    assert "It lost money because of hail." in view.checks_html
    assert view.checks_html.count('class="fail"') == 3
    assert view.checks_html.count('class="pass"') == 2 * len(CHECKS) - 3
    assert "name a cause your records don" in view.checks_html


def test_rejected_try_before_a_passing_one_stays_folded():
    view = build_view(
        _result(
            narration=_outcome(
                context="Weather explains only part of it.",
                failed=[("unsupported_cause",)],
                rejected=["It lost money because of hail."],
            )
        )
    )
    assert "AI sentence withheld" not in view.answer_html
    assert "passed all 9 checks on try 2" in view.checks_html
    assert view.checks_summary == "All 9 passed on try 2 \u00b7 AI sentence shown"
    assert view.checks_open is False
    assert '<details class="pf-rejected">' in view.checks_html


def test_nothing_to_add_is_not_called_withheld():
    view = build_view(_result())
    assert "AI sentence withheld" not in view.answer_html
    assert "nothing to add" in view.checks_html


def test_answer_card_leaves_out_the_therefore_line():
    # The card shows only what was calculated and what the AI added; the
    # terminal's "Therefore:" restatement is not part of it.
    view = build_view(_result(narration=_outcome(context="The weather explains part of it.")))
    assert "What that means" not in view.answer_html
    assert "pf-line-therefore" not in view.answer_html
    assert "isolated to 2020" not in view.answer_html


def test_figures_show_evidence_and_label_modeled_estimate():
    view = build_view(_result())
    assert "Bad year (a one-season outlier)" in view.figures_html
    assert "$68.19" in view.figures_html
    assert "Modeled estimate, not a measurement" in view.figures_html
    assert "resolved_0002" not in view.figures_html  # internal ids stay hidden


def test_cost_table_drops_repeated_context_and_flags_outlier():
    view = build_view(_result(payload=COST))
    assert "Sheyenne Bottom" not in view.figures_html.split("</table>")[0]  # repeated column dropped
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


def test_answer_shows_which_question_was_answered():
    html = build_view(_result()).answer_html
    assert '<div class="pf-resolved"><p><span>Talking about:</span> East 80' in html
    assert html.index("pf-resolved") < html.index("Your answer")
    # "New subject" sits on that line: it's there whenever there is a subject.
    assert '<button type="button" class="pf-newsub"' in html
    assert html.index("pf-newsub") < html.index("Your answer")


def test_tool_refusal_also_shows_what_was_looked_up():
    view = build_view(
        AnswerResult(
            text="no field named 'Easy 80' was found in the record (code: not_found)",
            ok=False,
            query=QueryObject(intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR, field_name="Easy 80"),
            tool_args={"field_name": "Easy 80"},
            refusal_kind="tool_refused",
        )
    )
    assert "Talking about:</span> Easy 80" in view.answer_html


def test_unresolved_follow_up_refusal_has_a_plain_title():
    view = build_view(
        AnswerResult(text="Try naming both.", ok=False, refusal_kind="unresolved_followup")
    )
    assert "wasn&#x27;t sure which field or season you meant" in view.answer_html
    assert "pf-resolved" not in view.answer_html


NITROGEN = {
    "field_name": "Section Corner",
    "asked_name": "Section Corner",
    "nitrogen_by_season": [
        {"season": 2023, "field_name": "Section Corner", "crop": "corn",
         "product": "UAN 32% (32-0-0)", "n_lb_n_ac": 160.6, "as_logged_rate": 45.38,
         "as_logged_unit": "gal/ac", "converted": True},
    ],
    "nitrogen_by_crop": {
        "corn": {"num_seasons": 2, "min_lb_n_ac": 141.3, "min_season": 2025,
                 "max_lb_n_ac": 160.6, "max_season": 2023, "spread_lb_n_ac": 19.3},
    },
    "logs_start_season": 2022,
    "uan32_lb_n_per_gal": 3.5392,
    "provenance": {"source_file_count": 137},
}


def test_nitrogen_figures_show_seasons_crops_and_conversion():
    html = build_view(_result(payload=NITROGEN)).figures_html
    assert "Nitrogen range by crop" in html and "corn" in html
    assert ">2022<" in html and ">2025<" in html  # years, not "2,022"
    assert "45.38" in html and "gal/ac" in html
    assert "3.5392" in html


def test_whole_percent_is_signed():
    assert format_value("pct_vs_farm_average", -60) == "-60%"


def test_empty_page_has_no_new_subject_button():
    assert "pf-newsub" not in empty_view().answer_html


def test_a_refusal_still_shows_what_the_next_question_builds_on():
    from farm_model.query_schema import FollowUpContext

    from farm_web.view import with_subject

    refused = build_view(
        AnswerResult(text="Try naming both.", ok=False, refusal_kind="unresolved_followup")
    )
    ctx = FollowUpContext(
        field_name="East 80", season=2020, intent=QueryIntent.BAD_FIELD_OR_BAD_YEAR
    )
    html = with_subject(refused, ctx).answer_html
    assert "Talking about:</span> East 80 \u00b7 2020" in html and "pf-newsub" in html
    assert with_subject(refused, None) == refused  # nothing remembered, no button
    shown = build_view(_result())
    assert with_subject(shown, ctx) == shown  # its own line wins, never two


def test_panels_fold_to_one_summary_line():
    from farm_web.view import checks_panel_html, numbers_panel_html

    view = build_view(_result(narration=_outcome(context="The weather explains part of it.")))
    checks = checks_panel_html(view)
    assert checks.startswith('<details class="pf-fold">')  # closed when all passed
    assert "All 9 passed \u00b7 AI sentence shown" in checks
    numbers = numbers_panel_html(view)
    assert numbers.startswith('<details class="pf-fold">')
    assert "1 modeled estimate" in numbers and "Where it came from" in numbers
    assert view.figures_tone == "ok"


def test_flagged_figures_say_so_on_the_folded_line():
    view = build_view(_result(payload=COST))
    assert "something flagged" in view.figures_summary and view.figures_tone == "warn"


def test_refusal_panels_say_nothing_to_check():
    view = build_view(AnswerResult(text="x", ok=False, refusal_kind="model_unreachable"))
    assert view.checks_summary == "Nothing to check" and view.checks_open is False


def test_show_the_records_lists_each_file_and_labels_the_whole_farm():
    payload = {
        **EAST_80,
        "provenance": {"data_dir": "/x/data/synthetic", "built_at": "2026-11-16T20:57:07", "source_file_count": 161},
    }
    records = [
        {"kind": "cost_ledger", "label": "Cost ledger", "path": "cost_ledger.xlsx", "tab": "2020",
         "rows": 1, "count_text": "1 row", "which": "row 3"},
        {"kind": "yield_monitor", "label": "Yield monitor", "path": "yield_monitor/y.csv", "tab": None,
         "rows": 250, "count_text": "250 points", "which": ""},
    ]
    html = build_view(_result(payload=payload, records=records)).source_html
    assert "Show the records" in html
    assert "cost_ledger.xlsx</code> &middot; tab <strong>2020</strong>" in html
    assert "row 3" in html and "250 points" in html and "all of it" in html
    assert "Records behind this answer" in html and "2 files and tabs" in html
    assert "161 files and tabs, every field and season" in html
    assert "of your files" not in html


def test_no_records_list_means_no_show_the_records():
    assert "Show the records" not in build_view(_result()).source_html
