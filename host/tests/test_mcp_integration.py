"""Phase 4 verification: wrapping farm_core in the MCP protocol must not
change a single computed number, and malformed input must come back as a
structured refusal, never a crash or a leaked traceback.

Each test opens its own MCPFleet within a single `async with` block rather
than sharing one across a session-scoped fixture: anyio's stdio_client uses
task-bound cancel scopes internally, and pytest-asyncio's generator-fixture
teardown can run in a different task than its setup, which anyio rejects
outright ("Attempted to exit cancel scope in a different task than it was
entered in"). Keeping open/use/close within one task/test sidesteps that
entirely -- the ~1-2s per-server startup cost is worth paying per test for
that robustness.
"""

import json
from pathlib import Path

from farm_core import pipeline
from farm_core.audit import AuditLog
from farm_core.profitability import bad_field_or_bad_year, which_fields_made_money
from farm_core.reconciliation import reconcile_yield_vs_scale
from farm_core.zone_profitability import (
    compute_zone_profitability,
    unprofitable_zones_in_profitable_fields,
)
from farm_host.mcp_client import MCPFleet

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "synthetic"
CONFIRM_STORE_PATH = REPO_ROOT / "data" / "confirmed_mappings.json"
# Loaded the same way every MCP server loads its snapshot -- from whatever
# farm-ingest already persisted -- so "matches direct call" is a genuine
# apples-to-apples comparison, not one side quietly using a less-confirmed
# resolution than the other.
DIRECT_SNAPSHOT = pipeline.load_query_time_snapshot(
    DATA_DIR, CONFIRM_STORE_PATH, AuditLog(REPO_ROOT / "data" / "audit.jsonl")
)


async def test_which_fields_made_money_matches_direct_call():
    seasons = [2021, 2022, 2023, 2024, 2025]
    async with MCPFleet(["report-export"]) as fleet:
        tool_result = await fleet.call("report-export", "which_fields_made_money", seasons=seasons)
    mcp_result = tool_result.data
    direct_result = which_fields_made_money(DIRECT_SNAPSHOT.profit_records, seasons)
    assert mcp_result["results"] == direct_result


async def test_bad_field_and_bad_year_match_direct_calls_through_mcp():
    marginal_id = DIRECT_SNAPSHOT.canonical_id_for_name("Marginal Eighty")
    catastrophic_id = DIRECT_SNAPSHOT.canonical_id_for_name("East 80")

    async with MCPFleet(["report-export"]) as fleet:
        mcp_marginal = (await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="Marginal Eighty"
        )).data
        mcp_catastrophic = (await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="East 80"
        )).data

    direct_marginal = bad_field_or_bad_year(DIRECT_SNAPSHOT.profit_records, marginal_id)
    direct_catastrophic = bad_field_or_bad_year(DIRECT_SNAPSHOT.profit_records, catastrophic_id)

    assert mcp_marginal["verdict"] == "bad_field" == direct_marginal["verdict"]
    assert mcp_marginal["evidence"] == direct_marginal["evidence"]
    assert mcp_catastrophic["verdict"] == "bad_year" == direct_catastrophic["verdict"]
    assert (
        mcp_catastrophic["evidence"]["outlier_seasons"]
        == direct_catastrophic["evidence"]["outlier_seasons"]
    )


async def test_report_export_structured_refusals_and_annotations():
    async with MCPFleet(["report-export"]) as fleet:
        bad_season = (
            await fleet.call("report-export", "which_fields_made_money", seasons=[1999])
        ).data
        assert bad_season["code"] == "invalid_input"

        empty_seasons = (
            await fleet.call("report-export", "which_fields_made_money", seasons=[])
        ).data
        assert empty_seasons["code"] == "invalid_input"

        unknown_field = (await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="Not A Real Field"
        )).data
        assert unknown_field["code"] == "not_found"

        tools = await fleet.sessions["report-export"].list_tools()
        by_name = {t.name: t for t in tools.tools}
        assert by_name["which_fields_made_money"].annotations.read_only_hint is True
        assert by_name["bad_field_or_bad_year"].annotations.read_only_hint is True
        assert by_name["export_profitability"].annotations.read_only_hint is False


async def test_export_is_write_gated_through_mcp(tmp_path):
    out_path = tmp_path / "export.json"
    async with MCPFleet(["report-export"]) as fleet:
        blocked = (await fleet.call("report-export", "export_profitability", path=str(out_path))).data
        assert blocked["code"] == "write_not_allowed"
        assert not out_path.exists()

        allowed = (await fleet.call(
            "report-export", "export_profitability", path=str(out_path), allow_write=True
        )).data
        assert allowed["exported_to"] == str(out_path)
    assert out_path.exists()


async def test_field_registry_resolution_matches_direct():
    async with MCPFleet(["field-registry"]) as fleet:
        mcp_result = (await fleet.call(
            "field-registry", "resolve_field_name", raw_name="north eighty", season=2017
        )).data
    expected = DIRECT_SNAPSHOT.alias_map[(2017, "north eighty")]
    assert mcp_result["canonical_boundary_name"] == expected


async def test_yield_reconciliation_matches_direct():
    direct = reconcile_yield_vs_scale(DIRECT_SNAPSHOT.con)
    match = next(r for r in direct if r.field_name == "Coulee Field" and r.season == 2021)

    async with MCPFleet(["yield-history"]) as fleet:
        mcp_result = (await fleet.call(
            "yield-history", "get_yield_reconciliation", field_name="Coulee Field", season=2021
        )).data
    assert mcp_result["totals_discrepancy"] == match.totals_discrepancy
    assert abs(mcp_result["pct_diff"] - match.pct_diff) < 1e-9


async def test_unknown_field_in_cost_ledger_server_refused():
    async with MCPFleet(["cost-ledger"]) as fleet:
        result = (await fleet.call(
            "cost-ledger", "get_cost_ledger_row", field_name="Not A Real Field", season=2020
        )).data
    assert result["code"] == "not_found"


async def test_as_applied_returns_empty_not_error_for_older_season():
    async with MCPFleet(["as-applied"]) as fleet:
        result = (await fleet.call(
            "as-applied", "get_as_applied_events", field_name="West 120", season=2016
        )).data
    assert result["events"] == []


async def test_as_applied_structured_refusal_for_unknown_season():
    async with MCPFleet(["as-applied"]) as fleet:
        result = (await fleet.call(
            "as-applied", "get_as_applied_events", field_name="West 120", season=1999
        )).data
    assert result["code"] == "invalid_input"


async def test_yield_history_structured_refusals():
    async with MCPFleet(["yield-history"]) as fleet:
        not_found = (await fleet.call(
            "yield-history",
            "get_yield_reconciliation",
            field_name="Not A Real Field",
            season=2021,
        )).data
        assert not_found["code"] == "not_found"

        invalid_season = (
            await fleet.call("yield-history", "list_yield_reconciliation", season=1999)
        ).data
        assert invalid_season["code"] == "invalid_input"


async def test_get_season_weather_returns_a_real_aggregate():
    async with MCPFleet(["weather-history"]) as fleet:
        result = (await fleet.call("weather-history", "get_season_weather", season=2018)).data
    assert result["total_precip_mm"] > 0
    assert result["heat_stress_days"] >= 0


async def test_get_season_weather_structured_refusal_for_unknown_season():
    async with MCPFleet(["weather-history"]) as fleet:
        result = (await fleet.call("weather-history", "get_season_weather", season=1999)).data
    assert result["code"] == "invalid_input"


async def test_get_field_soil_resolves_a_naming_drift_alias():
    async with MCPFleet(["weather-history"]) as fleet:
        result = (
            await fleet.call("weather-history", "get_field_soil", field_name="north eighty")
        ).data
    assert result["field_name"] == "N 80"
    assert result["awc_in"] > 0


async def test_get_field_soil_structured_refusal_for_unknown_field():
    async with MCPFleet(["weather-history"]) as fleet:
        result = (
            await fleet.call("weather-history", "get_field_soil", field_name="Not A Real Field")
        ).data
    assert result["code"] == "not_found"


async def test_bad_field_or_bad_year_carries_weather_attribution_for_the_forced_drought():
    ground_truth = json.loads((DATA_DIR / "ground_truth.json").read_text())
    ws = ground_truth["weathershortfall"]
    name = ground_truth["canonical_fields"][ws["field_id"]]["display_name_by_season"][
        str(ws["season"])
    ]

    async with MCPFleet(["report-export"]) as fleet:
        result = (
            await fleet.call("report-export", "bad_field_or_bad_year", field_name=name)
        ).data

    assert result["verdict"] == "bad_year"
    entries = {a["season"]: a for a in result["modeled"]["attribution"]}
    assert ws["season"] in entries
    entry = entries[ws["season"]]
    assert entry["calibrated"] is True
    assert abs(entry["season_effect"]) > abs(entry["residual"]), (
        "the forced drought should be explained mostly by weather, not left as residual"
    )


async def test_zone_profitability_matches_direct_call():
    ground_truth = json.loads((DATA_DIR / "ground_truth.json").read_text())
    bad_zone = ground_truth["bad_zone"]
    name = ground_truth["canonical_fields"][bad_zone["field_id"]]["display_name_by_season"][
        str(bad_zone["season"])
    ]
    canonical_id = DIRECT_SNAPSHOT.canonical_id_for_name(name)

    async with MCPFleet(["report-export"]) as fleet:
        mcp_result = (
            await fleet.call(
                "report-export", "zone_profitability", field_name=name, season=bad_zone["season"]
            )
        ).data

    direct_result = compute_zone_profitability(DIRECT_SNAPSHOT, canonical_id, bad_zone["season"])
    assert mcp_result["field_profit"] == direct_result.field_profit
    assert [z["profit"] for z in mcp_result["zones"]] == [z.profit for z in direct_result.zones]


async def test_zone_profitability_shows_def_badzone_as_negative():
    ground_truth = json.loads((DATA_DIR / "ground_truth.json").read_text())
    bad_zone = ground_truth["bad_zone"]
    name = ground_truth["canonical_fields"][bad_zone["field_id"]]["display_name_by_season"][
        str(bad_zone["season"])
    ]

    async with MCPFleet(["report-export"]) as fleet:
        result = (
            await fleet.call(
                "report-export", "zone_profitability", field_name=name, season=bad_zone["season"]
            )
        ).data

    target = result["zones"][bad_zone["zone_index"]]
    assert target["available"] is True
    assert target["profit"] < 0
    assert result["field_profit"] > 0


async def test_zone_profitability_structured_refusal_for_uncovered_season():
    async with MCPFleet(["report-export"]) as fleet:
        result = (
            await fleet.call(
                "report-export", "zone_profitability", field_name="West 120", season=2016
            )
        ).data
    assert result["code"] == "invalid_input"


async def test_zone_profitability_structured_refusal_for_unknown_field():
    async with MCPFleet(["report-export"]) as fleet:
        result = (
            await fleet.call(
                "report-export",
                "zone_profitability",
                field_name="Not A Real Field",
                season=2024,
            )
        ).data
    assert result["code"] == "not_found"


async def test_unprofitable_zones_summary_matches_direct_call():
    async with MCPFleet(["report-export"]) as fleet:
        mcp_result = (
            await fleet.call("report-export", "unprofitable_zones_in_profitable_fields")
        ).data
    direct_result = unprofitable_zones_in_profitable_fields(DIRECT_SNAPSHOT)
    assert (
        mcp_result["pct_acres_unprofitable_in_profitable_fields"]
        == direct_result["pct_acres_unprofitable_in_profitable_fields"]
    )
    assert mcp_result["acres_examined"] == direct_result["acres_examined"]
