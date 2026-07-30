"""One canonical end-to-end build: ingest every raw source, resolve field
identity and naming-drift aliases, compute profitability. Every MCP server
and the CLI call this rather than each reimplementing the ingest-resolve-
compute sequence.
"""

from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path

import duckdb

from . import (
    alias_resolution,
    confirm as confirm_mod,
    db,
    field_identity,
    governance,
    ingest_as_applied,
    ingest_boundaries,
    ingest_cost_ledger,
    ingest_cost_ledger_names,
    ingest_scale_tickets,
    ingest_unit_prices,
    ingest_weather,
    ingest_yield_monitor,
    profitability,
)
from .audit import AuditLog

SEASONS = list(range(2016, 2026))


@dataclasses.dataclass
class FarmSnapshot:
    con: duckdb.DuckDBPyConnection
    identity: field_identity.FieldIdentityResolution
    alias_map: dict[tuple[int, str], str]
    profit_records: dict[tuple[str, int], profitability.ProfitRecord]
    seasons: list[int]
    data_dir: Path
    built_at: str
    source_files: list[str]

    def canonical_id_for_name(self, field_name: str) -> str | None:
        """Resolves a farmer-supplied name to a canonical field, trying the
        exact spellings first and only widening the match if none succeed:
        1. exact stable boundary name
        2. exact naming-drift alias (a spelling the ledger itself used)
        3. case-insensitive versions of both -- a farmer typing "marginal
           eighty" for "Marginal Eighty" isn't a genuine ambiguity the way
           the naming-drift word-vs-digit spellings are, so normalizing case
           is a safe, fully deterministic widening, not a guess.
        """
        for lineage in self.identity.lineages.values():
            if field_name in lineage.display_name_by_season.values():
                return lineage.canonical_id
        for (_season, raw_name), canonical_name in self.alias_map.items():
            if raw_name == field_name:
                return self.canonical_id_for_name(canonical_name)

        folded = field_name.casefold()
        for lineage in self.identity.lineages.values():
            if folded in {n.casefold() for n in lineage.display_name_by_season.values()}:
                return lineage.canonical_id
        for (_season, raw_name), canonical_name in self.alias_map.items():
            if raw_name.casefold() == folded:
                return self.canonical_id_for_name(canonical_name)
        return None


def build_farm_snapshot(data_dir: Path, confirm_fn: confirm_mod.ConfirmFn) -> FarmSnapshot:
    con = db.connect()

    ingest_boundaries.ingest_boundaries(con, data_dir)
    ingest_cost_ledger_names.ingest_cost_ledger_field_names(con, data_dir)
    ingest_cost_ledger.ingest_cost_ledger(con, data_dir, confirm_fn)
    ingest_unit_prices.ingest_unit_prices(con, data_dir)
    ingest_scale_tickets.ingest_scale_tickets(con, data_dir)
    ingest_yield_monitor.ingest_yield_monitor(con, data_dir)
    ingest_as_applied.ingest_as_applied(con, data_dir)
    ingest_weather.ingest_weather(con, data_dir)

    identity = field_identity.resolve_field_identity(con, SEASONS, confirm_fn)
    aliases = alias_resolution.resolve_all_aliases(con, SEASONS, confirm_fn)
    alias_map = {(a.season, a.raw_field_name): a.canonical_boundary_name for a in aliases}

    profit_records = profitability.compute_profitability(con, identity, alias_map)

    source_files = sorted(
        {
            row[0]
            for table in (
                "boundary_fields",
                "cost_ledger_rows",
                "scale_ticket_loads",
                "yield_monitor_points",
                "as_applied_events",
                "weather_daily",
                "soil_awc",
            )
            for row in con.execute(f"SELECT DISTINCT source_file FROM {table}").fetchall()
        }
    )

    return FarmSnapshot(
        con=con,
        identity=identity,
        alias_map=alias_map,
        profit_records=profit_records,
        seasons=SEASONS,
        data_dir=data_dir,
        built_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_files=source_files,
    )


class SnapshotUnconfirmed(Exception):
    """Raised by load_query_time_snapshot when building the snapshot hits a
    naming-drift alias, identity event, or column mapping with no persisted
    decision. Carries the ConfirmationRequest that blocked it so a caller
    (an MCP server tool function) can report exactly what's unconfirmed and
    that `farm-ingest` is how to confirm it -- an MCP server is a
    non-interactive stdio subprocess, so it can never resolve this itself.
    """

    def __init__(self, request: confirm_mod.ConfirmationRequest):
        self.request = request
        super().__init__(
            f"unconfirmed: {request.kind} {request.key!r} -- run `farm-ingest` to confirm it"
        )


def load_query_time_snapshot(
    data_dir: Path, confirm_store_path: Path, audit_log: AuditLog
) -> FarmSnapshot:
    """The only way an MCP server should build a FarmSnapshot: reuses
    whatever farm-ingest already confirmed and persisted, and refuses
    (SnapshotUnconfirmed) rather than guessing at anything it didn't.
    """
    gate = governance.ConfirmationGate(confirm_store_path, confirm_mod.refuse_unconfirmed, audit_log)
    try:
        return build_farm_snapshot(data_dir, confirm_fn=gate)
    except confirm_mod.ConfirmationRejected as e:
        if e.request is None:
            raise  # not a pending-confirmation case (e.g. a structurally ambiguous
            # source file) -- a real error, not something farm-ingest can resolve
        raise SnapshotUnconfirmed(e.request) from e
