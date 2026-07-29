"""Phase 2 verification: every remaining defect ID that reconciliation is
responsible for is detected and handled per its ground-truth
expected_detection, with no meaningful false-positive noise drowning out the
real signal.
"""

import pytest

from farm_core import reconciliation


@pytest.fixture(scope="module")
def yield_reconciliation(full_ingest):
    return reconciliation.reconcile_yield_vs_scale(full_ingest["con"])


@pytest.fixture(scope="module")
def cost_reconciliation(full_ingest):
    return reconciliation.reconcile_cost_ledger_vs_as_applied(
        full_ingest["con"], full_ingest["alias_map"]
    )


def _calibration_defects(ground_truth):
    return {
        (d["field_id"], d["season"])
        for d in ground_truth["defects"]
        if d["type"] == "yield_monitor_calibration_error"
    }


def test_every_calibration_error_defect_is_flagged(yield_reconciliation, ground_truth):
    expected = _calibration_defects(ground_truth)
    gt_fields = ground_truth["canonical_fields"]
    expected_field_season = {
        (gt_fields[fid]["display_name_by_season"][str(season)], season) for fid, season in expected
    }
    flagged = {(r.field_name, r.season) for r in yield_reconciliation if r.totals_discrepancy}
    assert flagged == expected_field_season


def test_calibration_flags_include_both_directions(yield_reconciliation):
    flagged = [r for r in yield_reconciliation if r.totals_discrepancy]
    assert any(r.pct_diff > 0 for r in flagged)
    assert any(r.pct_diff < 0 for r in flagged)


def test_missing_swath_is_flagged_via_coverage_not_totals(yield_reconciliation, ground_truth):
    swath_defect = next(d for d in ground_truth["defects"] if d["type"] == "missing_swath")
    gt_fields = ground_truth["canonical_fields"]
    field_name = gt_fields[swath_defect["field_id"]]["display_name_by_season"][
        str(swath_defect["season"])
    ]

    match = next(
        r
        for r in yield_reconciliation
        if r.field_name == field_name and r.season == swath_defect["season"]
    )
    assert match.coverage_gap_flagged
    # The defining property of this defect: totals still reconcile normally,
    # so a totals-only check would have missed it.
    assert not match.totals_discrepancy


def test_no_monitor_seasons_have_no_totals_data(yield_reconciliation, ground_truth):
    no_monitor_seasons = {
        d["season"] for d in ground_truth["defects"] if d["type"] == "no_yield_monitor"
    }
    for r in yield_reconciliation:
        if r.season in no_monitor_seasons:
            assert r.monitor_total_bu is None
            assert not r.totals_discrepancy
            assert not r.coverage_gap_flagged


def test_false_positive_rate_is_low(yield_reconciliation, ground_truth):
    """Only the deliberately injected defects should be flagged -- if
    everything looks like an outlier, the signal is worthless.
    """
    expected_count = len(
        [d for d in ground_truth["defects"] if d["type"] == "yield_monitor_calibration_error"]
    )
    flagged = [r for r in yield_reconciliation if r.totals_discrepancy]
    assert len(flagged) == expected_count


def test_transposed_digit_is_the_dominant_cost_outlier(cost_reconciliation, ground_truth):
    digit_defect = next(d for d in ground_truth["defects"] if d["type"] == "transposed_digit")
    gt_fields = ground_truth["canonical_fields"]
    field_name = gt_fields[digit_defect["field_id"]]["display_name_by_season"][
        str(digit_defect["season"])
    ]

    outliers = [r for r in cost_reconciliation if r.outlier_flagged]
    assert len(outliers) >= 1
    match = next(
        r for r in outliers if r.field_name == field_name and r.season == digit_defect["season"]
    )
    assert match.line_item == "seed"
    # It should be the single worst outlier by magnitude, not just any flag.
    assert abs(match.pct_diff) == max(abs(r.pct_diff) for r in outliers)


def test_cost_reconciliation_outlier_rate_is_low(cost_reconciliation):
    """With rates/prices shared between the ledger and as-applied logs, only
    the one deliberate defect should stand out -- not systemic noise.
    """
    outliers = [r for r in cost_reconciliation if r.outlier_flagged]
    assert len(outliers) <= 2  # generous margin above the exactly-one-defect baseline


def test_unit_conversion_does_not_bias_fertilizer_outliers_by_season(cost_reconciliation):
    """DEF-UNIT seasons alternate lb/ac vs gal/ac N recording. If the gal/ac
    -> lb/ac conversion were missing or wrong, every gal/ac season would show
    a large systematic fertilizer mismatch (~3.5x, the UAN conversion
    factor) that lb/ac seasons wouldn't -- that would show up as outliers
    concentrated in alternating seasons, not as isolated noise.
    """
    fert = [r for r in cost_reconciliation if r.line_item == "fertilizer"]
    by_season_avg_abs_diff = {}
    for r in fert:
        by_season_avg_abs_diff.setdefault(r.season, []).append(abs(r.pct_diff))
    averages = {s: sum(vs) / len(vs) for s, vs in by_season_avg_abs_diff.items()}
    # No season's average fertilizer discrepancy should approach the ~250%
    # magnitude an unconverted 3.5x unit error would produce.
    assert all(avg < 1.0 for avg in averages.values())
