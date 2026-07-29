"""Ingest per-field, per-season yield monitor point CSVs. The file itself
carries no field name or season column -- like real combine monitor exports,
identity is carried by the filename convention. The season is trivially
parsed from the filename; the field name requires matching the filename's
slug against that season's known active boundary field names, since the slug
transform is lossy and not directly invertible.

Absent for the two oldest seasons (older combine, scale tickets only) -- that
absence is expected, not an ingestion error, and is handled by the caller
simply finding no files for those seasons.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from . import db as db_mod

_FILENAME_RE = re.compile(r"yield_monitor_(?P<slug>.+)_(?P<season>\d{4})\.csv$")


def _slugify(name: str) -> str:
    """Must exactly match the generator's slug transform (generator/src/
    farm_data_gen/yield_monitor.py) for filename matching to work.
    """
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


def _field_name_for_slug(slug: str, season_names: list[str], filename: str) -> str:
    matches = [name for name in season_names if _slugify(name) == slug]
    if len(matches) == 0:
        raise ValueError(
            f"{filename}: slug {slug!r} doesn't match any active field name for its season"
        )
    if len(matches) > 1:
        raise ValueError(
            f"{filename}: slug {slug!r} matches multiple field names {matches} -- ambiguous"
        )
    return matches[0]


def ingest_yield_monitor(con: duckdb.DuckDBPyConnection, data_dir: Path) -> int:
    """Field-name resolution (from the filename slug) stays in Python -- it's
    cheap, one query per file. The actual row data is loaded through DuckDB's
    native CSV reader in a single INSERT...SELECT per file rather than parsed
    row-by-row in Python: for ~36k points across ~90 files that's the
    difference between low seconds and tens of seconds.
    """
    total = 0
    for path in sorted((data_dir / "yield_monitor").glob("yield_monitor_*.csv")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(f"Unrecognized yield monitor filename: {path.name}")
        season = int(match.group("season"))
        slug = match.group("slug")

        season_names = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT field_name FROM boundary_fields WHERE season = ?", [season]
            ).fetchall()
        ]
        field_name = _field_name_for_slug(slug, season_names, path.name)

        db_mod.delete_source(con, "yield_monitor_points", path.name)
        con.execute(
            """
            INSERT INTO yield_monitor_points
            SELECT
                ? AS field_name,
                ? AS season,
                timestamp,
                lat,
                lon,
                wet_bu_ac,
                dry_bu_ac,
                moisture_pct,
                ? AS source_file
            FROM read_csv_auto(?)
            """,
            [field_name, season, path.name, str(path)],
        )
        total += con.execute(
            "SELECT count(*) FROM yield_monitor_points WHERE source_file = ?", [path.name]
        ).fetchone()[0]
    return total
