"""DuckDB connection and schema. Originals on disk are never touched -- every
table here is a copy-on-ingest of raw file contents, keyed by source_file so a
re-ingest of the same file is idempotent (delete-then-insert) rather than
accumulating duplicates.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS boundary_fields (
    season INTEGER NOT NULL,
    field_name VARCHAR NOT NULL,
    acres DOUBLE NOT NULL,
    crop VARCHAR NOT NULL,
    min_lon DOUBLE NOT NULL,
    max_lon DOUBLE NOT NULL,
    min_lat DOUBLE NOT NULL,
    max_lat DOUBLE NOT NULL,
    source_crs VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_ledger_field_names (
    season INTEGER NOT NULL,
    raw_field_name VARCHAR NOT NULL,
    acres DOUBLE NOT NULL,
    row_index INTEGER NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_ledger_rows (
    season INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    raw_field_name VARCHAR NOT NULL,
    crop VARCHAR NOT NULL,
    acres DOUBLE NOT NULL,
    seed_cost_per_ac DOUBLE NOT NULL,
    fertilizer_cost_per_ac DOUBLE NOT NULL,
    chemical_cost_per_ac DOUBLE NOT NULL,
    fuel_cost_per_ac DOUBLE NOT NULL,
    cash_rent_per_ac DOUBLE NOT NULL,
    cost_basis VARCHAR NOT NULL,        -- 'per_acre' | 'total_dollars' (as declared by the header)
    notes VARCHAR,
    mapping_version VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS unit_prices (
    season INTEGER NOT NULL,
    seed_corn_price_per_unit DOUBLE NOT NULL,
    seed_soybean_price_per_unit DOUBLE NOT NULL,
    n_price_per_lb DOUBLE NOT NULL,
    p_price_per_lb DOUBLE NOT NULL,
    k_price_per_lb DOUBLE NOT NULL,
    chemical_price_per_ac DOUBLE NOT NULL,
    fuel_price_per_gal DOUBLE NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS yield_monitor_points (
    field_name VARCHAR NOT NULL,
    season INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    lat DOUBLE NOT NULL,
    lon DOUBLE NOT NULL,
    wet_bu_ac DOUBLE NOT NULL,
    dry_bu_ac DOUBLE NOT NULL,
    moisture_pct DOUBLE NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS scale_ticket_loads (
    season INTEGER NOT NULL,
    ticket_number INTEGER NOT NULL,
    date DATE NOT NULL,
    field_name VARCHAR NOT NULL,
    crop VARCHAR NOT NULL,
    load_number INTEGER NOT NULL,
    moisture_pct DOUBLE NOT NULL,
    gross_bushels DOUBLE NOT NULL,
    net_bushels DOUBLE NOT NULL,
    price_per_bu DOUBLE NOT NULL,
    elevator VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS as_applied_events (
    season INTEGER NOT NULL,
    field_name VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    product VARCHAR NOT NULL,
    rate DOUBLE NOT NULL,
    rate_unit VARCHAR NOT NULL,
    lat DOUBLE NOT NULL,
    lon DOUBLE NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_daily (
    season INTEGER NOT NULL,
    date DATE NOT NULL,
    precip_mm DOUBLE NOT NULL,
    temp_min_c DOUBLE NOT NULL,
    temp_max_c DOUBLE NOT NULL,
    source_file VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS soil_awc (
    field_name VARCHAR NOT NULL,
    awc_in DOUBLE NOT NULL,
    source_file VARCHAR NOT NULL
);
"""


def connect(db_path: str | Path = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    con.execute(_SCHEMA)
    return con


def replace_rows(
    con: duckdb.DuckDBPyConnection, table: str, source_file: str, rows: list[dict]
) -> None:
    """Idempotent ingest: drop any prior rows from this exact source_file, then
    insert the new ones. Re-running ingestion on an unchanged file is a no-op
    in effect; on a changed file it fully replaces that file's contribution.

    Uses one batched INSERT (all rows as a single parameterized statement)
    rather than executemany, which pays a per-row Python/C-API round trip --
    for a table the size of yield_monitor_points that difference is the gap
    between sub-second and tens of seconds.
    """
    delete_source(con, table, source_file)
    if not rows:
        return
    columns = list(rows[0].keys())
    row_placeholder = "(" + ", ".join("?" for _ in columns) + ")"
    values_sql = ", ".join(row_placeholder for _ in rows)
    flat_params = [row[c] for row in rows for c in columns]
    con.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES {values_sql}",
        flat_params,
    )


def delete_source(con: duckdb.DuckDBPyConnection, table: str, source_file: str) -> None:
    con.execute(f"DELETE FROM {table} WHERE source_file = ?", [source_file])
