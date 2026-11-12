"""Automated version of docs/EVAL_QUESTIONS.md's evaluation questions.
Each is independent, read-only, and checked against a single verifiable
figure from data/synthetic/ground_truth.json (seed 42) -- see that doc for
the full rationale behind each question's inclusion.

Dollar figures are pinned twice: as exact pipeline goldens (regression), and
against ground_truth.json within a few cents. The answer key is computed from
the same cent-rounded values the raw files record, so any gap beyond float
rounding means the pipeline (or the generator) changed behavior.
"""

import json
from pathlib import Path

from farm_host.mcp_client import MCPFleet

_GROUND_TRUTH = json.loads(
    (Path(__file__).resolve().parents[2] / "data" / "synthetic" / "ground_truth.json").read_text()
)
# Per field-season the pipeline matches the key to within 2 cents (float
# rounding at a half-cent boundary); multi-season totals accumulate that.
_CENTS_PER_SEASON = 0.02


def _gt_profit(display_name: str, season: int) -> float:
    for root_id, field in _GROUND_TRUTH["canonical_fields"].items():
        if field["display_name_by_season"].get(str(season)) == display_name:
            return _GROUND_TRUTH["profitability"][root_id][str(season)]["profit"]
    raise KeyError((display_name, season))


def _assert_matches_ground_truth(display_name: str, seasons: list[int], pipeline_total: float):
    expected = round(sum(_gt_profit(display_name, s) for s in seasons), 2)
    assert abs(pipeline_total - expected) <= _CENTS_PER_SEASON * len(seasons) + 1e-9, (
        f"{display_name} {seasons}: pipeline {pipeline_total} vs ground truth {expected}"
    )


async def test_q1_marginal_field_is_a_chronic_loss_pattern():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="Marginal Eighty"
        )
    r = result.data
    assert r["verdict"] == "bad_field"
    assert r["evidence"]["loss_rate"] == 1.0


async def test_q2_east_80_is_a_genuine_one_season_outlier():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call("report-export", "bad_field_or_bad_year", field_name="East 80")
    r = result.data
    assert r["verdict"] == "bad_year"
    assert r["evidence"]["outlier_seasons"] == [2020]
    assert r["evidence"]["median_profit_per_acre"] == 68.19  # doc: $68.19


async def test_q3_south_160_south_is_a_normal_unremarkable_field():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="South 160 South"
        )
    r = result.data
    assert r["verdict"] == "consistently_profitable"
    assert r["evidence"]["loss_rate"] == 0.17
    assert r["evidence"]["num_loss_seasons"] == 1
    assert r["evidence"]["num_seasons"] == 6


async def test_q4_ranking_over_relative_five_year_window():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call(
            "report-export", "which_fields_made_money", seasons=[2021, 2022, 2023, 2024, 2025]
        )
    r = result.data
    assert r["results"][0]["display_name"] == "East 80"
    assert r["results"][0]["total_profit"] == 135533.57
    _assert_matches_ground_truth("East 80", [2021, 2022, 2023, 2024, 2025],
                                 r["results"][0]["total_profit"])
    assert r["results"][-1]["display_name"] == "Marginal Eighty"
    assert r["results"][-1]["total_profit"] == -112044.65
    _assert_matches_ground_truth("Marginal Eighty", [2021, 2022, 2023, 2024, 2025],
                                 r["results"][-1]["total_profit"])
    assert r["num_fields"] == len(r["results"])
    assert r["num_fields_made_money"] == sum(1 for x in r["results"] if x["total_profit"] > 0)


async def test_q5_ranking_over_explicit_named_years():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call("report-export", "which_fields_made_money", seasons=[2019, 2020])
    r = result.data
    assert r["results"][0]["display_name"] == "Depot Forty"
    assert r["results"][0]["total_profit"] == 17551.4
    _assert_matches_ground_truth("Depot Forty", [2019, 2020], r["results"][0]["total_profit"])


async def test_q6_naming_drift_resolution():
    async with MCPFleet(["field-registry"]) as fleet:
        result = await fleet.call(
            "field-registry", "resolve_field_name", raw_name="north eighty", season=2017
        )
    r = result.data
    assert r["canonical_boundary_name"] == "N 80"
    assert r["method"] == "alias"


async def test_q7_home_quarter_2019_monitor_disagrees_with_scale_tickets():
    """The doc's eval 7 (DEF-CAL-2019-root_03): +6.9%, 5,008 vs 4,684 bu."""
    async with MCPFleet(["yield-history"]) as fleet:
        result = await fleet.call(
            "yield-history", "get_yield_reconciliation", field_name="Home Quarter", season=2019
        )
    r = result.data
    assert r["totals_discrepancy"] is True
    assert round(r["pct_diff"] * 100, 1) == 6.9
    assert round(r["monitor_total_bu"]) == 5008
    assert round(r["scale_total_bu"]) == 4684


async def test_q7b_coulee_field_2021_negative_calibration_error():
    """A second, negative-direction calibration defect (DEF-CAL-2021-root_11)."""
    async with MCPFleet(["yield-history"]) as fleet:
        result = await fleet.call(
            "yield-history", "get_yield_reconciliation", field_name="Coulee Field", season=2021
        )
    r = result.data
    assert r["totals_discrepancy"] is True
    assert round(r["pct_diff"] * 100, 1) == -3.4
    # Display rounding at the server layer: no 15-digit floats reach the user.
    assert r["monitor_total_bu"] == round(r["monitor_total_bu"], 1)
    assert r["scale_total_bu"] == round(r["scale_total_bu"], 1)
    assert r["pct_diff"] == round(r["pct_diff"], 4)


async def test_q8_coverage_gap_totals_alone_would_miss():
    async with MCPFleet(["yield-history"]) as fleet:
        result = await fleet.call(
            "yield-history",
            "get_yield_reconciliation",
            field_name="Marginal Eighty",
            season=2024,
        )
    r = result.data
    assert r["coverage_gap_flagged"] is True
    assert r["totals_discrepancy"] is False


async def test_q9_ledger_entry_does_not_match_its_own_inputs():
    async with MCPFleet(["cost-ledger"]) as fleet:
        result = await fleet.call(
            "cost-ledger", "get_cost_reconciliation", field_name="Riverside", season=2022
        )
    r = result.data
    seed = next(item for item in r["results"] if item["line_item"] == "seed")
    assert seed["outlier_flagged"] is True
    assert seed["ledger_cost_per_ac"] == 95.55


async def test_q10_field_that_no_longer_exists_is_refused_not_guessed():
    async with MCPFleet(["field-registry"]) as fleet:
        result = await fleet.call(
            "field-registry", "resolve_field_name", raw_name="Township Rd 12", season=2020
        )
        last_season = await fleet.call(
            "field-registry", "resolve_field_name", raw_name="Township Rd 12", season=2019
        )
    r = result.data
    assert r["code"] == "not_found"
    # The boundary is exact: the lease ended after 2019, so 2019 still resolves.
    assert "code" not in last_season.data
