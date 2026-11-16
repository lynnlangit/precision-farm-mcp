"""farm_host.records: every lookup the app can run lists the records it read."""

from farm_core.records_behind import KINDS
from farm_host.cli import _INTENT_TO_TOOL
from farm_host.records import SOURCES_BY_TOOL, records_request


def test_every_tool_the_app_routes_to_has_its_records_listed():
    assert set(_INTENT_TO_TOOL.values()) <= set(SOURCES_BY_TOOL)
    for kinds in SOURCES_BY_TOOL.values():
        assert set(kinds) <= set(KINDS)


def test_request_carries_field_and_seasons():
    assert records_request("get_yield_reconciliation", {"field_name": "East 80", "season": 2019}, {}) == {
        "kinds": ["yield_monitor", "scale_tickets", "boundaries"],
        "field_name": "East 80",
        "seasons": [2019],
    }
    assert records_request("which_fields_made_money", {"seasons": [2024, 2025]}, {})["seasons"] == [2024, 2025]
    assert "field_name" not in records_request("unprofitable_zones_in_profitable_fields", {}, {})
    assert records_request("not_a_tool", {}, {}) is None


def test_bad_year_estimate_adds_weather_and_soil():
    plain = records_request("bad_field_or_bad_year", {"field_name": "East 80"}, {})
    modeled = records_request(
        "bad_field_or_bad_year", {"field_name": "East 80"}, {"modeled": {"attribution": [{}]}}
    )
    assert "weather" not in plain["kinds"]
    assert {"weather", "soil"} <= set(modeled["kinds"])


def test_your_records_worked_example_matches_farm_1():
    # docs/YOUR_RECORDS.md walks through Marginal Eighty 2025 on Farm 1 by
    # hand; the figures there must be the ones the tool computes.
    from pathlib import Path

    import pytest

    from farm_core import confirm, pipeline
    from farm_core.records_behind import records_behind

    clean = Path(__file__).resolve().parents[2] / "data" / "synthetic-clean"
    if not (clean / "cost_ledger.xlsx").exists():
        pytest.skip("Farm 1 data not generated")
    snap = pipeline.build_farm_snapshot(clean, confirm.auto_approve)
    rec = snap.profit_records[(snap.canonical_id_for_name("Marginal Eighty"), 2025)]
    doc = (Path(__file__).resolve().parents[2] / "docs" / "YOUR_RECORDS.md").read_text()
    assert f"{rec.acres} acres" in doc
    assert f"${rec.revenue:,.2f}" in doc
    assert f"**−${-rec.profit:,.2f}**" in doc
    assert f"${-rec.profit_per_acre:,.2f} per acre" in doc
    assert f"{len(snap.source_files)} for Farm 1" in doc
    found = {
        r["kind"]: r["which"]
        for r in records_behind(snap, ["cost_ledger", "scale_tickets"], "Marginal Eighty", [2025])
    }
    assert f"tab `2025`, {found['cost_ledger']}" in doc
    first, last = found["scale_tickets"].removeprefix("tickets ").split("-")
    assert f"tickets {first} to {last}" in doc
