"""Phase A / A2 verification: every tool's successful response carries the
`modeled` subtree -- the structural boundary that keeps a future Phase C
model output from ever silently blending into today's measured/derived
data. Nothing is modeled yet, so `modeled` is always None here; the point is
that the field exists on every response now, before Phase C needs it.
"""

from farm_host.mcp_client import MCPFleet


async def test_every_successful_response_carries_the_modeled_field():
    calls = [
        ("report-export", "which_fields_made_money", {"seasons": [2021, 2022, 2023]}),
        ("report-export", "bad_field_or_bad_year", {"field_name": "Marginal Eighty"}),
        ("field-registry", "resolve_field_identity", {}),
        ("field-registry", "resolve_field_name", {"raw_name": "N 80", "season": 2020}),
        ("yield-history", "get_yield_reconciliation", {"field_name": "Coulee Field", "season": 2021}),
        ("yield-history", "list_yield_reconciliation", {"season": 2021}),
        ("as-applied", "get_as_applied_events", {"field_name": "West 120", "season": 2023}),
        (
            "cost-ledger",
            "get_cost_ledger_row",
            {"field_name": "West 120", "season": 2020},
        ),
        (
            "cost-ledger",
            "get_cost_reconciliation",
            {"field_name": "Riverside", "season": 2022},
        ),
    ]
    servers = sorted({server for server, _, _ in calls})

    async with MCPFleet(servers) as fleet:
        for server, tool, kwargs in calls:
            result = (await fleet.call(server, tool, **kwargs)).data
            assert "error" not in result, f"{server}.{tool} unexpectedly refused: {result}"
            assert "modeled" in result, f"{server}.{tool} response is missing the modeled field"
            assert result["modeled"] is None  # nothing populates it until Phase C
