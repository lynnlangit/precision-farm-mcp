"""Ingest elevator scale ticket CSVs, one file per season. field_name in this
file is always the stable boundary name (never the cost ledger's drifting
alias), so no resolution is needed here -- straight ingestion via DuckDB's
native CSV reader (fast, no per-row Python parsing).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from . import db as db_mod


def ingest_scale_tickets(con: duckdb.DuckDBPyConnection, data_dir: Path) -> int:
    total = 0
    for path in sorted((data_dir / "scale_tickets").glob("scale_tickets_*.csv")):
        db_mod.delete_source(con, "scale_ticket_loads", path.name)
        con.execute(
            """
            INSERT INTO scale_ticket_loads
            SELECT
                season,
                ticket_number,
                date,
                field_name,
                crop,
                load_number,
                moisture_pct,
                gross_bushels,
                net_bushels,
                price_per_bu,
                elevator,
                ? AS source_file
            FROM read_csv_auto(?)
            """,
            [path.name, str(path)],
        )
        total += con.execute(
            "SELECT count(*) FROM scale_ticket_loads WHERE source_file = ?", [path.name]
        ).fetchone()[0]
    return total
