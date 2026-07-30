"""Ingest synthetic daily weather and static soil available-water-capacity
(AWC). Weather is season-wide -- no field_name at all, so no naming
ambiguity to resolve. Soil AWC is keyed by the field's current display
name, but that's resolved to a canonical_id downstream the same way
as-applied events are (FarmSnapshot.canonical_id_for_name), not at ingest
time -- so, like ingest_as_applied.py, this needs no confirmation.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import duckdb

from . import db as db_mod

_FILENAME_RE = re.compile(r"weather_(\d{4})\.csv$")


def ingest_weather(con: duckdb.DuckDBPyConnection, data_dir: Path) -> int:
    total = 0
    weather_dir = data_dir / "weather"

    for path in sorted(weather_dir.glob("weather_*.csv")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(f"Unrecognized weather filename: {path.name}")
        season = int(match.group(1))

        with path.open(encoding="utf-8", newline="") as f:
            rows = [
                {
                    "season": season,
                    "date": r["date"],
                    "precip_mm": float(r["precip_mm"]),
                    "temp_min_c": float(r["temp_min_c"]),
                    "temp_max_c": float(r["temp_max_c"]),
                    "source_file": path.name,
                }
                for r in csv.DictReader(f)
            ]
        db_mod.replace_rows(con, "weather_daily", path.name, rows)
        total += len(rows)

    soil_path = weather_dir / "soil_awc.csv"
    if soil_path.exists():
        with soil_path.open(encoding="utf-8", newline="") as f:
            rows = [
                {
                    "field_name": r["field_name"],
                    "awc_in": float(r["awc_in"]),
                    "source_file": soil_path.name,
                }
                for r in csv.DictReader(f)
            ]
        db_mod.replace_rows(con, "soil_awc", soil_path.name, rows)
        total += len(rows)

    return total
