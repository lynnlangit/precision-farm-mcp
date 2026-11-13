"""Farm 1 in the grower web app: the same farm as data/synthetic/ (Farm 2),
generated with --clean, so its records have none of Farm 2's record-keeping
mistakes. Tool level, no model (test_eval_nl.py asks the same questions in
plain English).

Each test asks a docs/EVAL_QUESTIONS.md question of both farms. Where the
question is about the farm itself (profit, bad field or bad year, zones) the
answers are identical; where it is about the records (do they agree, does a
cost look right, what does a misspelling mean) Farm 1's pass and Farm 2's
are caught. That contrast is what growers see when they switch farms.

Needs Farm 1's data and mappings; skipped otherwise:

    uv run --project generator python -m farm_data_gen.cli --seed 42 --clean --out data/synthetic-clean
    uv run --project host farm-ingest --auto-approve-synthetic-only \\
        --data-dir data/synthetic-clean --confirm-store data/confirmed_mappings_clean.json
"""

import json

import pytest

from farm_host.farms import FARMS
from farm_host.mcp_client import MCPFleet

FARM1, FARM2 = FARMS["farm1"], FARMS["farm2"]

pytestmark = pytest.mark.skipif(
    not (FARM1.data_dir / "ground_truth.json").is_file() or not FARM1.confirm_store.is_file(),
    reason="Farm 1 data not generated/ingested (see this file's docstring)",
)


async def _ask(farm, server: str, tool: str, **args) -> dict:
    async with MCPFleet([server], env_overrides=farm.server_env()) as fleet:
        return (await fleet.call(server, tool, **args)).data


async def _both(server: str, tool: str, **args) -> tuple[dict, dict]:
    return await _ask(FARM1, server, tool, **args), await _ask(FARM2, server, tool, **args)


def test_farm1_is_the_same_farm_with_clean_records():
    gt1 = json.loads((FARM1.data_dir / "ground_truth.json").read_text())
    gt2 = json.loads((FARM2.data_dir / "ground_truth.json").read_text())
    assert gt1["generator"]["clean_records"] is True
    assert gt1["profitability"] == gt2["profitability"]  # one answer key for both
    assert gt1["canonical_fields"] == gt2["canonical_fields"]
    record_defects = {"naming_drift", "ambiguous_alias_tie", "yield_monitor_calibration_error",
                      "missing_swath", "transposed_digit", "unit_inconsistency",
                      "prompt_injection_notes", "no_yield_monitor", "cost_basis_total_dollars",
                      "spreadsheet_merged_header", "spreadsheet_totals_row_in_range",
                      "spreadsheet_blank_rows"}
    assert not record_defects & {d["type"] for d in gt1["defects"]}
    assert record_defects <= {d["type"] for d in gt2["defects"]}


async def test_same_answer_on_both_farms_when_the_question_is_about_the_farm():
    for tool, args in [
        ("bad_field_or_bad_year", {"field_name": "Marginal Eighty"}),
        ("bad_field_or_bad_year", {"field_name": "East 80"}),
        ("zone_profitability", {"field_name": "Section Corner", "season": 2024}),
    ]:
        f1, f2 = await _both("report-export", tool, **args)
        f1.pop("provenance", None), f2.pop("provenance", None)
        assert f1 == f2, (tool, args)
    assert f1["field_profit"] == 5897.56  # Q11's golden, on both farms

    # Q4's ranking: same top and bottom (only Home Quarter's 2023 differs, below).
    f1, f2 = await _both("report-export", "which_fields_made_money",
                         seasons=[2021, 2022, 2023, 2024, 2025])
    for i in (0, -1):
        assert f1["results"][i] == f2["results"][i]
    assert f1["results"][0]["total_profit"] == 135533.57


async def test_q6_misspelled_name_only_exists_on_the_messy_farm():
    f1, f2 = await _both("field-registry", "resolve_field_name", raw_name="north eighty", season=2017)
    assert f1["code"] == "not_found"  # Farm 1's ledger always says "N 80"
    assert (f2["canonical_boundary_name"], f2["method"]) == ("N 80", "alias")


async def test_q7_yield_monitor_agrees_on_farm1_and_is_caught_on_farm2():
    f1, f2 = await _both(
        "yield-history", "get_yield_reconciliation", field_name="Home Quarter", season=2019
    )
    assert f1["totals_discrepancy"] is False
    assert (f1["monitor_total_bu"], f1["scale_total_bu"]) == (4696.1, 4683.5)
    assert f2["totals_discrepancy"] is True
    assert f2["scale_total_bu"] == f1["scale_total_bu"]  # same harvest, different monitor


async def test_q8_no_coverage_gap_on_farm1():
    f1, f2 = await _both(
        "yield-history", "get_yield_reconciliation", field_name="Marginal Eighty", season=2024
    )
    assert f1["coverage_gap_flagged"] is False
    assert f2["coverage_gap_flagged"] is True


async def test_q9_seed_cost_is_right_on_farm1_and_flagged_on_farm2():
    f1, f2 = await _both(
        "cost-ledger", "get_cost_reconciliation", field_name="Sheyenne Bottom", season=2022
    )
    seed1 = next(i for i in f1["results"] if i["line_item"] == "seed")
    seed2 = next(i for i in f2["results"] if i["line_item"] == "seed")
    assert (seed1["ledger_cost_per_ac"], seed1["outlier_flagged"]) == (59.55, False)
    assert (seed2["ledger_cost_per_ac"], seed2["outlier_flagged"]) == (95.55, True)
    assert not any(i["outlier_flagged"] for i in f1["results"])


async def test_q10_lost_lease_is_refused_on_both_farms():
    f1, f2 = await _both("field-registry", "resolve_field_name", raw_name="Township Rd 12", season=2020)
    assert f1["code"] == f2["code"] == "not_found"


async def test_auto_approved_misspelling_costs_farm2_a_season_of_home_quarter():
    """DEF-ALIASTIE: auto-approving 'Hom Corner' (synthetic setup only) files
    Home Quarter's 2023 costs under the wrong field, so Farm 2 sees 9 seasons
    of Home Quarter where Farm 1 sees all 10 -- why a person confirms names."""
    f1, f2 = await _both("report-export", "bad_field_or_bad_year", field_name="Home Quarter")
    assert f1["evidence"]["num_seasons"] == 10
    assert f2["evidence"]["num_seasons"] == 9
