"""Phase C4 verification: the relative expectation model must actually tell
a weather-caused shortfall apart from a management-caused one, using the two
deliberately forced scenarios (DEF-WEATHERSHORTFALL, DEF-MGMTSHORTFALL) the
generator guarantees regardless of --seed -- see docs/PROJECT_HISTORY.md's
Phase C3. If it can't tell them apart, the world model is decorative.
"""

import pytest

from farm_core import expectation


def _field_name(ground_truth, field_id, season):
    return ground_truth["canonical_fields"][field_id]["display_name_by_season"][str(season)]


def test_weathershortfall_season_effect_dominates_the_residual(farm_snapshot, ground_truth):
    ws = ground_truth["weathershortfall"]
    name = _field_name(ground_truth, ws["field_id"], ws["season"])
    canonical_id = farm_snapshot.canonical_id_for_name(name)
    assert canonical_id is not None

    result = expectation.compute_attribution(farm_snapshot, canonical_id, ws["season"])

    assert result.season_effect < 0, "the forced drought must show up as a negative season effect"
    assert abs(result.season_effect) > abs(result.residual), (
        "weather should explain most of the shortfall -- season_effect must dominate residual"
    )


def test_mgmtshortfall_residual_dominates_the_season_effect(farm_snapshot, ground_truth):
    ms = ground_truth["mgmtshortfall"]
    name = _field_name(ground_truth, ms["field_id"], ms["season"])
    canonical_id = farm_snapshot.canonical_id_for_name(name)
    assert canonical_id is not None

    result = expectation.compute_attribution(farm_snapshot, canonical_id, ms["season"])

    assert result.residual < 0, "the forced management override must show up as a negative residual"
    assert abs(result.residual) > abs(result.season_effect), (
        "weather was ordinary that season -- residual (unexplained) must dominate season_effect"
    )


def test_the_two_defects_are_told_apart_from_each_other(farm_snapshot, ground_truth):
    """The actual distinguishing claim: which effect dominates flips between
    the two scenarios -- not just that each individually looks a certain way.
    """
    ws = ground_truth["weathershortfall"]
    ms = ground_truth["mgmtshortfall"]
    ws_result = expectation.compute_attribution(
        farm_snapshot,
        farm_snapshot.canonical_id_for_name(_field_name(ground_truth, ws["field_id"], ws["season"])),
        ws["season"],
    )
    ms_result = expectation.compute_attribution(
        farm_snapshot,
        farm_snapshot.canonical_id_for_name(_field_name(ground_truth, ms["field_id"], ms["season"])),
        ms["season"],
    )

    ws_weather_share = abs(ws_result.season_effect) / (
        abs(ws_result.season_effect) + abs(ws_result.residual)
    )
    ms_weather_share = abs(ms_result.season_effect) / (
        abs(ms_result.season_effect) + abs(ms_result.residual)
    )
    assert ws_weather_share > ms_weather_share, (
        "the weather-caused shortfall must be attributed more to weather than the "
        "management-caused one is"
    )


def test_refuses_when_a_field_has_too_little_history(farm_snapshot):
    # South 160 (the un-split parent lineage) has only 4 active seasons --
    # below MIN_SEASONS_FOR_BASELINE's effective floor for a *reliable* mean,
    # but still above it; use a genuinely short-lived lineage instead: the
    # merged field only has 4 seasons, right at the boundary. Pick a lineage
    # with fewer seasons than the minimum by construting the check directly.
    short_lineages = [
        cid
        for cid, lineage in farm_snapshot.identity.lineages.items()
        if len(lineage.active_seasons) < expectation.MIN_SEASONS_FOR_BASELINE
    ]
    if not short_lineages:
        pytest.skip("no lineage in this run has fewer than MIN_SEASONS_FOR_BASELINE seasons")
    canonical_id = short_lineages[0]
    season = farm_snapshot.identity.lineages[canonical_id].active_seasons[0]

    with pytest.raises(expectation.AttributionUnavailable):
        expectation.compute_attribution(farm_snapshot, canonical_id, season)


def test_refuses_for_a_season_with_no_yield_data(farm_snapshot):
    any_lineage = next(iter(farm_snapshot.identity.lineages))
    with pytest.raises(expectation.AttributionUnavailable):
        expectation.compute_attribution(farm_snapshot, any_lineage, 1999)


def test_backtest_reports_a_real_error_measure_over_the_whole_farm(farm_snapshot):
    result = expectation.backtest(farm_snapshot)
    assert result["attributed"] > 0
    assert result["mae"] is not None
    assert result["mae"] >= 0
    assert result["rmse"] >= result["mae"]  # RMSE never below MAE, by definition
