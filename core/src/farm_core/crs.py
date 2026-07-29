"""CRS normalization: farm boundary files declare either EPSG:4326 (lon/lat) or
EPSG:26914 (NAD83 / UTM zone 14N). Every downstream comparison needs a single
common frame, so everything gets normalized to lon/lat on ingest.

This inverts the same simple planar approximation the synthetic generator uses
to go the other way (see generator/src/farm_data_gen/boundaries.py) -- not a
true Transverse Mercator implementation, but internally consistent, which is
all that matters for the acreage/bbox continuity checks in field_identity.py.
A real deployment would swap this for pyproj against the farmer's actual CRS.
"""

from __future__ import annotations

import math

_METERS_PER_DEGREE_LAT = 111_320.0
_UTM_FALSE_EASTING = 500_000.0
_UTM_K0 = 0.9996
_UTM_CENTRAL_MERIDIAN = -99.0  # EPSG:26914 zone 14N


def _meters_per_degree_lon(lat: float) -> float:
    return _METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))


def utm26914_to_lonlat(easting: float, northing: float) -> tuple[float, float]:
    lat = northing / (_METERS_PER_DEGREE_LAT * _UTM_K0)
    lon = _UTM_CENTRAL_MERIDIAN + (easting - _UTM_FALSE_EASTING) / (
        _meters_per_degree_lon(lat) * _UTM_K0
    )
    return lon, lat


def crs_name_to_epsg(crs_member: dict) -> str:
    """GeoJSON legacy crs member -> a short code like 'EPSG:4326'."""
    name = crs_member.get("properties", {}).get("name", "")
    if "4326" in name:
        return "EPSG:4326"
    if "26914" in name:
        return "EPSG:26914"
    raise ValueError(f"Unrecognized CRS: {name!r}")


def to_lonlat(x: float, y: float, epsg: str) -> tuple[float, float]:
    if epsg == "EPSG:4326":
        return x, y
    if epsg == "EPSG:26914":
        return utm26914_to_lonlat(x, y)
    raise ValueError(f"Unsupported CRS: {epsg!r}")
