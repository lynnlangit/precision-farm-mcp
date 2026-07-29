"""Ingest the shared 'Unit Prices' tab of cost_ledger.xlsx -- one row per
season, clean fixed columns, no ambiguity, no confirmation needed.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import openpyxl

from . import db as db_mod

_EXPECTED_HEADER = [
    "Season",
    "Seed Corn ($/unit)",
    "Seed Soybean ($/unit)",
    "N ($/lb)",
    "P ($/lb)",
    "K ($/lb)",
    "Chemical ($/ac)",
    "Fuel ($/gal)",
]


def ingest_unit_prices(con: duckdb.DuckDBPyConnection, data_dir: Path) -> int:
    path = data_dir / "cost_ledger.xlsx"
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["Unit Prices"]
    rows = list(ws.iter_rows(values_only=True))

    header = list(rows[0])
    if header != _EXPECTED_HEADER:
        raise ValueError(f"Unexpected Unit Prices header: {header}")

    db_rows = [
        {
            "season": row[0],
            "seed_corn_price_per_unit": row[1],
            "seed_soybean_price_per_unit": row[2],
            "n_price_per_lb": row[3],
            "p_price_per_lb": row[4],
            "k_price_per_lb": row[5],
            "chemical_price_per_ac": row[6],
            "fuel_price_per_gal": row[7],
            "source_file": "cost_ledger.xlsx::Unit Prices",
        }
        for row in rows[1:]
        if row and row[0] is not None
    ]
    db_mod.replace_rows(con, "unit_prices", "cost_ledger.xlsx::Unit Prices", db_rows)
    return len(db_rows)
