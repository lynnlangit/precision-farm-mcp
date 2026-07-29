"""Ingest as-applied input logs, one file per season (last 4 seasons only).
The season isn't a column in the CSV -- it's carried by the filename, the
same convention real ag equipment software uses.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import duckdb

from . import db as db_mod

_FILENAME_RE = re.compile(r"as_applied_(\d{4})\.csv$")


def ingest_as_applied(con: duckdb.DuckDBPyConnection, data_dir: Path) -> int:
    total = 0
    for path in sorted((data_dir / "as_applied").glob("as_applied_*.csv")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(f"Unrecognized as-applied filename: {path.name}")
        season = int(match.group(1))

        with path.open(encoding="utf-8", newline="") as f:
            rows = [
                {
                    "season": season,
                    "field_name": r["field_name"],
                    "timestamp": r["timestamp"],
                    "product": r["product"],
                    "rate": float(r["rate"]),
                    "rate_unit": r["rate_unit"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                    "source_file": path.name,
                }
                for r in csv.DictReader(f)
            ]
        db_mod.replace_rows(con, "as_applied_events", path.name, rows)
        total += len(rows)
    return total
