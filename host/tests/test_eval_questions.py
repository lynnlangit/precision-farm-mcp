"""Automated version of docs/EVAL_QUESTIONS.md's 10 evaluation questions.
Each is independent, read-only, and checked against a single verifiable
figure from data/synthetic/ground_truth.json (seed 42) -- see that doc for
the full rationale behind each question's inclusion.
"""

from farm_host.mcp_client import MCPFleet


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
    assert r["evidence"]["median_profit_per_acre"] == 139.24


async def test_q3_west_120_is_a_normal_unremarkable_field():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call("report-export", "bad_field_or_bad_year", field_name="West 120")
    r = result.data
    assert r["verdict"] == "consistently_profitable"
    assert r["evidence"]["loss_rate"] == 0.3


async def test_q4_ranking_over_relative_five_year_window():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call(
            "report-export", "which_fields_made_money", seasons=[2021, 2022, 2023, 2024, 2025]
        )
    r = result.data
    assert r["results"][0]["display_name"] == "East 80"
    assert r["results"][0]["total_profit"] == 162146.32
    assert r["results"][-1]["display_name"] == "Marginal Eighty"
    assert r["results"][-1]["total_profit"] == -87773.68


async def test_q5_ranking_over_explicit_named_years():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call("report-export", "which_fields_made_money", seasons=[2019, 2020])
    r = result.data
    assert r["results"][0]["display_name"] == "Depot Forty"
    assert r["results"][0]["total_profit"] == 44527.24


async def test_q6_naming_drift_resolution():
    async with MCPFleet(["field-registry"]) as fleet:
        result = await fleet.call(
            "field-registry", "resolve_field_name", raw_name="north eighty", season=2017
        )
    r = result.data
    assert r["canonical_boundary_name"] == "N 80"
    assert r["method"] == "alias"


async def test_q7_genuine_yield_monitor_discrepancy():
    async with MCPFleet(["yield-history"]) as fleet:
        result = await fleet.call(
            "yield-history", "get_yield_reconciliation", field_name="Coulee Field", season=2021
        )
    r = result.data
    assert r["totals_discrepancy"] is True
    assert round(r["pct_diff"] * 100, 1) == -3.4


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
            "field-registry", "resolve_field_name", raw_name="Township Rd 12", season=2021
        )
    r = result.data
    assert r["code"] == "not_found"
