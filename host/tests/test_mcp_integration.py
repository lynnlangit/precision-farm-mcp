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

from pathlib import Path

from farm_core.pipeline import build_farm_snapshot
from farm_core.profitability import bad_field_or_bad_year, which_fields_made_money
from farm_core.reconciliation import reconcile_yield_vs_scale
from farm_host.mcp_client import MCPFleet

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
DIRECT_SNAPSHOT = build_farm_snapshot(DATA_DIR)


async def test_which_fields_made_money_matches_direct_call():
    seasons = [2021, 2022, 2023, 2024, 2025]
    async with MCPFleet(["report-export"]) as fleet:
        mcp_result = await fleet.call("report-export", "which_fields_made_money", seasons=seasons)
    direct_result = which_fields_made_money(DIRECT_SNAPSHOT.profit_records, seasons)
    assert mcp_result["results"] == direct_result


async def test_bad_field_and_bad_year_match_direct_calls_through_mcp():
    marginal_id = DIRECT_SNAPSHOT.canonical_id_for_name("Marginal Eighty")
    catastrophic_id = DIRECT_SNAPSHOT.canonical_id_for_name("East 80")

    async with MCPFleet(["report-export"]) as fleet:
        mcp_marginal = await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="Marginal Eighty"
        )
        mcp_catastrophic = await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="East 80"
        )

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
        bad_season = await fleet.call("report-export", "which_fields_made_money", seasons=[1999])
        assert bad_season["code"] == "invalid_input"

        empty_seasons = await fleet.call("report-export", "which_fields_made_money", seasons=[])
        assert empty_seasons["code"] == "invalid_input"

        unknown_field = await fleet.call(
            "report-export", "bad_field_or_bad_year", field_name="Not A Real Field"
        )
        assert unknown_field["code"] == "not_found"

        tools = await fleet.sessions["report-export"].list_tools()
        by_name = {t.name: t for t in tools.tools}
        assert by_name["which_fields_made_money"].annotations.read_only_hint is True
        assert by_name["bad_field_or_bad_year"].annotations.read_only_hint is True
        assert by_name["export_profitability"].annotations.read_only_hint is False


async def test_export_is_write_gated_through_mcp(tmp_path):
    out_path = tmp_path / "export.json"
    async with MCPFleet(["report-export"]) as fleet:
        blocked = await fleet.call("report-export", "export_profitability", path=str(out_path))
        assert blocked["code"] == "write_not_allowed"
        assert not out_path.exists()

        allowed = await fleet.call(
            "report-export", "export_profitability", path=str(out_path), allow_write=True
        )
        assert allowed["exported_to"] == str(out_path)
    assert out_path.exists()


async def test_field_registry_resolution_matches_direct():
    async with MCPFleet(["field-registry"]) as fleet:
        mcp_result = await fleet.call(
            "field-registry", "resolve_field_name", raw_name="north eighty", season=2017
        )
    expected = DIRECT_SNAPSHOT.alias_map[(2017, "north eighty")]
    assert mcp_result["canonical_boundary_name"] == expected


async def test_yield_reconciliation_matches_direct():
    direct = reconcile_yield_vs_scale(DIRECT_SNAPSHOT.con)
    match = next(r for r in direct if r.field_name == "Coulee Field" and r.season == 2021)

    async with MCPFleet(["yield-history"]) as fleet:
        mcp_result = await fleet.call(
            "yield-history", "get_yield_reconciliation", field_name="Coulee Field", season=2021
        )
    assert mcp_result["totals_discrepancy"] == match.totals_discrepancy
    assert abs(mcp_result["pct_diff"] - match.pct_diff) < 1e-9


async def test_unknown_field_in_cost_ledger_server_refused():
    async with MCPFleet(["cost-ledger"]) as fleet:
        result = await fleet.call(
            "cost-ledger", "get_cost_ledger_row", field_name="Not A Real Field", season=2020
        )
    assert result["code"] == "not_found"


async def test_as_applied_returns_empty_not_error_for_older_season():
    async with MCPFleet(["as-applied"]) as fleet:
        result = await fleet.call(
            "as-applied", "get_as_applied_events", field_name="West 120", season=2016
        )
    assert result["events"] == []
