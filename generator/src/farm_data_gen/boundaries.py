"""Per-season GeoJSON field boundaries, in EPSG:4326 for most seasons and
EPSG:26914 (NAD83 / UTM zone 14N) for a subset -- real ag GIS exports mix CRS
across seasons/tools all the time, and downstream code has to handle it.

Geometry is a lightweight, deterministic rectangle model sized to match each
field's assigned acreage, laid out on a fixed grid around a base ND location.
The projection to EPSG:26914 is a simple planar approximation (not a true
Transverse Mercator implementation) -- it produces plausible, internally
consistent UTM-magnitude coordinates without adding a geodesy dependency. v1
does no spatial analysis on these coordinates, so approximate placement with
correct order of magnitude and a correctly declared CRS is what matters.
"""

from __future__ import annotations

import math

from . import rng as rng_mod
from .config import SimConfig
from .farm import FarmModel

_METERS_PER_DEGREE_LAT = 111_320.0
_UTM_FALSE_EASTING = 500_000.0
_UTM_K0 = 0.9996

_GRID_COLS = 4
_GRID_SPACING_M = 1400.0

_ACRE_TO_SQM = 4046.86


def _meters_per_degree_lon(lat: float) -> float:
    return _METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))


def _grid_center(slot_index: int, config: SimConfig) -> tuple[float, float]:
    row, col = divmod(slot_index, _GRID_COLS)
    dx_m = col * _GRID_SPACING_M
    dy_m = row * _GRID_SPACING_M
    lat = config.base_lat + dy_m / _METERS_PER_DEGREE_LAT
    lon = config.base_lon + dx_m / _meters_per_degree_lon(config.base_lat)
    return lat, lon


def _rectangle_lonlat(
    center_lat: float, center_lon: float, acres: float, aspect_ratio: float
) -> list[tuple[float, float]]:
    area_sqm = acres * _ACRE_TO_SQM
    height_m = math.sqrt(area_sqm / aspect_ratio)
    width_m = area_sqm / height_m
    half_h_deg = (height_m / 2) / _METERS_PER_DEGREE_LAT
    half_w_deg = (width_m / 2) / _meters_per_degree_lon(center_lat)
    ring = [
        (center_lon - half_w_deg, center_lat - half_h_deg),
        (center_lon + half_w_deg, center_lat - half_h_deg),
        (center_lon + half_w_deg, center_lat + half_h_deg),
        (center_lon - half_w_deg, center_lat + half_h_deg),
        (center_lon - half_w_deg, center_lat - half_h_deg),
    ]
    return ring


def _split_rectangle(
    ring: list[tuple[float, float]], fraction_a: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    lons = [p[0] for p in ring[:-1]]
    lats = [p[1] for p in ring[:-1]]
    width = max(lons) - min(lons)
    height = max(lats) - min(lats)
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    if width >= height:
        split_lon = min_lon + width * fraction_a
        ring_a = [
            (min_lon, min_lat),
            (split_lon, min_lat),
            (split_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat),
        ]
        ring_b = [
            (split_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (split_lon, max_lat),
            (split_lon, min_lat),
        ]
    else:
        split_lat = min_lat + height * fraction_a
        ring_a = [
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, split_lat),
            (min_lon, split_lat),
            (min_lon, min_lat),
        ]
        ring_b = [
            (min_lon, split_lat),
            (max_lon, split_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, split_lat),
        ]
    return ring_a, ring_b


def _to_utm26914(ring: list[tuple[float, float]], config: SimConfig) -> list[tuple[float, float]]:
    out = []
    for lon, lat in ring:
        easting = (
            _UTM_FALSE_EASTING
            + (lon - config.utm_central_meridian) * _meters_per_degree_lon(lat) * _UTM_K0
        )
        northing = lat * _METERS_PER_DEGREE_LAT * _UTM_K0
        out.append((round(easting, 2), round(northing, 2)))
    return out


_CRS_MEMBERS = {
    "EPSG:4326": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
    "EPSG:26914": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::26914"}},
}


def compute_field_rings(
    farm: FarmModel,
) -> dict[str, list[tuple[float, float]]]:
    """Compute a lon/lat ring per canonical field, splitting parent geometry
    for split children and combining parent geometry as a MultiPolygon member
    list for merged fields (handled by the caller).
    """
    config = farm.config
    rings: dict[str, list[tuple[float, float]]] = {}
    slot_by_root: dict[str, int] = {}
    slot_i = 0
    for field_id, field in sorted(farm.identity.canonical_fields.items()):
        if field.role in ("split_child",):
            continue  # derived from parent below
        if field.role == "merge_child":
            continue  # handled as multipolygon by caller
        r = rng_mod.derive_rng(config.random_seed, field_id, "aspect_ratio")
        aspect = float(r.uniform(0.6, 1.6))
        if field_id not in slot_by_root:
            slot_by_root[field_id] = slot_i
            slot_i += 1
        center_lat, center_lon = _grid_center(slot_by_root[field_id], config)
        acres = farm.acres_by_field[field_id]
        rings[field_id] = _rectangle_lonlat(center_lat, center_lon, acres, aspect)

    for event in farm.identity.events:
        if event.type == "split":
            (parent_id,) = event.parent_field_ids
            child_a_id, child_b_id = event.child_field_ids
            parent_ring = rings[parent_id]
            parent_acres = farm.acres_by_field[parent_id]
            a_acres = farm.acres_by_field[child_a_id]
            fraction_a = a_acres / parent_acres
            ring_a, ring_b = _split_rectangle(parent_ring, fraction_a)
            rings[child_a_id] = ring_a
            rings[child_b_id] = ring_b
        elif event.type == "merge":
            parent_a_id, parent_b_id = event.parent_field_ids
            (child_id,) = event.child_field_ids
            lons = [p[0] for r in (rings[parent_a_id], rings[parent_b_id]) for p in r[:-1]]
            lats = [p[1] for r in (rings[parent_a_id], rings[parent_b_id]) for p in r[:-1]]
            min_lon, max_lon, min_lat, max_lat = min(lons), max(lons), min(lats), max(lats)
            rings[child_id] = [
                (min_lon, min_lat),
                (max_lon, min_lat),
                (max_lon, max_lat),
                (min_lon, max_lat),
                (min_lon, min_lat),
            ]

    return rings


def build_boundaries_by_season(farm: FarmModel) -> dict[int, dict]:
    """Return {season: geojson_feature_collection_dict} for every season."""
    config = farm.config
    rings = compute_field_rings(farm)

    merge_parents: dict[str, tuple[str, str]] = {}
    for event in farm.identity.events:
        if event.type == "merge":
            (child_id,) = event.child_field_ids
            merge_parents[child_id] = tuple(event.parent_field_ids)

    out: dict[int, dict] = {}
    for season_index, season in enumerate(config.seasons):
        crs_name = "EPSG:26914" if season_index in config.utm_crs_season_indices else "EPSG:4326"
        features = []
        for field_id in farm.fields_active_in(season):
            name = farm.display_name(field_id, season)
            record = farm.record(field_id, season)

            if field_id in merge_parents:
                parent_a, parent_b = merge_parents[field_id]
                polygons_lonlat = [rings[parent_a], rings[parent_b]]
                if crs_name == "EPSG:26914":
                    polygons = [_to_utm26914(r, config) for r in polygons_lonlat]
                else:
                    polygons = polygons_lonlat
                geometry = {
                    "type": "MultiPolygon",
                    "coordinates": [[[list(pt) for pt in poly]] for poly in polygons],
                }
            else:
                ring = rings[field_id]
                coords = _to_utm26914(ring, config) if crs_name == "EPSG:26914" else ring
                geometry = {"type": "Polygon", "coordinates": [[list(pt) for pt in coords]]}

            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "field_name": name,
                        "acres": round(record.acres, 1),
                        "crop": record.crop,
                        "season": season,
                    },
                }
            )

        out[season] = {
            "type": "FeatureCollection",
            "crs": _CRS_MEMBERS[crs_name],
            "features": features,
        }

    return out
