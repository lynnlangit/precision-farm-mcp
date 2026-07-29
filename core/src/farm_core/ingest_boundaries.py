"""Ingest per-season field boundary GeoJSON into DuckDB, normalizing every
geometry's bounding box to lon/lat regardless of the season's declared CRS.

Deliberately extracts only what field_identity.py needs (name, acres, crop,
bbox) -- not full geometry -- since Phase 1 exists to prove field-identity
resolution, not to build a spatial engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from . import db as db_mod
from .crs import crs_name_to_epsg, to_lonlat


def _iter_ring_points(geometry: dict):
    if geometry["type"] == "Polygon":
        for ring in geometry["coordinates"]:
            yield from ring
    elif geometry["type"] == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            for ring in polygon:
                yield from ring
    else:
        raise ValueError(f"Unsupported geometry type: {geometry['type']}")


def _bbox_lonlat(geometry: dict, epsg: str) -> tuple[float, float, float, float]:
    lons: list[float] = []
    lats: list[float] = []
    for x, y in _iter_ring_points(geometry):
        lon, lat = to_lonlat(x, y, epsg)
        lons.append(lon)
        lats.append(lat)
    return min(lons), max(lons), min(lats), max(lats)


def ingest_boundaries(con: duckdb.DuckDBPyConnection, data_dir: Path) -> int:
    """Ingest every field_boundaries_*.geojson under data_dir/boundaries/.
    Returns the number of feature rows ingested.
    """
    boundaries_dir = data_dir / "boundaries"
    total = 0
    for path in sorted(boundaries_dir.glob("field_boundaries_*.geojson")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        epsg = crs_name_to_epsg(payload["crs"])

        rows = []
        for feature in payload["features"]:
            props = feature["properties"]
            min_lon, max_lon, min_lat, max_lat = _bbox_lonlat(feature["geometry"], epsg)
            rows.append(
                {
                    "season": props["season"],
                    "field_name": props["field_name"],
                    "acres": props["acres"],
                    "crop": props["crop"],
                    "min_lon": min_lon,
                    "max_lon": max_lon,
                    "min_lat": min_lat,
                    "max_lat": max_lat,
                    "source_crs": epsg,
                    "source_file": path.name,
                }
            )

        db_mod.replace_rows(con, "boundary_fields", path.name, rows)
        total += len(rows)

    return total
