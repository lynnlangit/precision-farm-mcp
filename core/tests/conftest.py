import json
from pathlib import Path

import pytest

from farm_core import (
    alias_resolution,
    confirm,
    db,
    field_identity,
    ingest_as_applied,
    ingest_boundaries,
    ingest_cost_ledger,
    ingest_cost_ledger_names,
    ingest_scale_tickets,
    ingest_unit_prices,
    ingest_yield_monitor,
    pipeline,
    profitability,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
SEASONS = list(range(2016, 2026))


@pytest.fixture(scope="session")
def ground_truth() -> dict:
    return json.loads((DATA_DIR / "ground_truth.json").read_text())


@pytest.fixture(scope="session")
def full_ingest():
    """Ingest all five raw sources plus naming-drift alias resolution once per
    test session -- every Phase 2 test reads from this shared connection.
    """
    con = db.connect()
    confirm_requests: list = []

    def logging_confirm(request):
        confirm_requests.append(request)
        return confirm.auto_approve(request)

    ingest_boundaries.ingest_boundaries(con, DATA_DIR)
    ingest_cost_ledger_names.ingest_cost_ledger_field_names(con, DATA_DIR)
    ingest_cost_ledger.ingest_cost_ledger(con, DATA_DIR, logging_confirm)
    ingest_unit_prices.ingest_unit_prices(con, DATA_DIR)
    ingest_scale_tickets.ingest_scale_tickets(con, DATA_DIR)
    ingest_yield_monitor.ingest_yield_monitor(con, DATA_DIR)
    ingest_as_applied.ingest_as_applied(con, DATA_DIR)

    aliases = alias_resolution.resolve_all_aliases(con, SEASONS, confirm.auto_approve)
    alias_map = {(a.season, a.raw_field_name): a.canonical_boundary_name for a in aliases}

    return {
        "con": con,
        "confirm_requests": confirm_requests,
        "aliases": aliases,
        "alias_map": alias_map,
    }


@pytest.fixture(scope="session")
def identity_resolution(full_ingest):
    return field_identity.resolve_field_identity(full_ingest["con"], SEASONS, confirm.auto_approve)


@pytest.fixture(scope="session")
def profit_records(full_ingest, identity_resolution):
    return profitability.compute_profitability(
        full_ingest["con"], identity_resolution, full_ingest["alias_map"]
    )


@pytest.fixture(scope="session")
def farm_snapshot():
    """A full FarmSnapshot (weather/soil included) built via the same
    pipeline.build_farm_snapshot every MCP server and the CLI use --
    separate from full_ingest above since expectation.py needs weather_daily
    and soil_awc, which that older, more narrowly-scoped fixture predates.
    """
    return pipeline.build_farm_snapshot(DATA_DIR, confirm.auto_approve)
