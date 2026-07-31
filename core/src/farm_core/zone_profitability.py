"""Zone-level profitability: grids each field into a fixed 2x2 set of
management zones and computes per-zone profit for the seasons that have
as-applied coverage, refusing rather than extrapolating for the rest.

Cost has no spatial resolution anywhere in this data model:
cost_ledger_rows is explicitly cost_basis="per_acre", field-wide by
construction, and as_applied_events has only 5 rows per field/season --
one per product, a single decorative lat/lon, a rate that's already
field-wide constant, not a spatial sample. So zone cost reuses the
field's own authoritative total_cost/acres (profitability.ProfitRecord)
uniformly across every zone. Only yield varies zone-to-zone, since
yield_monitor_points is the one table with genuine per-point spatial
resolution (hundreds of points per field). This is a deliberate
divergence from a literal "spatial join" -- see docs/ARCHITECTURE.md's
Diverged row.

Derived arithmetic, not modeled: nothing here belongs under the
`modeled` subtree.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .pipeline import FarmSnapshot

ZONE_GRID_ROWS = 2
ZONE_GRID_COLS = 2
ZONE_COUNT = ZONE_GRID_ROWS * ZONE_GRID_COLS
ZONE_MIN_POINTS = 10  # fewer points than this -> reported unavailable, not estimated


@dataclasses.dataclass(frozen=True)
class ZoneProfitEntry:
    zone_index: int
    acres: float
    available: bool
    point_count: int
    yield_bu_ac: float | None = None
    revenue: float | None = None
    cost: float | None = None
    profit: float | None = None
    unavailable_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ZoneProfitabilityResult:
    canonical_id: str
    season: int
    field_acres: float
    field_profit: float
    zones: list[ZoneProfitEntry]

    def to_json(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "season": self.season,
            "field_acres": self.field_acres,
            "field_profit": self.field_profit,
            "zones": [z.to_json() for z in self.zones],
        }


class ZoneProfitabilityUnavailable(Exception):
    """A whole-call refusal -- unknown field/season, no boundary or price
    data, or (most commonly) a season with no as_applied_events coverage
    at all. Per-zone insufficient coverage is not this: it's reported as
    one zone entry with available=False alongside sibling zones that do
    have enough points, never a reason to fail the whole call.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _as_applied_covered_seasons(snapshot: FarmSnapshot) -> list[int]:
    """Discovered from the data, never hardcoded -- the generator's
    --seasons/as_applied_seasons_count are configurable.
    """
    rows = snapshot.con.execute("SELECT DISTINCT season FROM as_applied_events").fetchall()
    return sorted(r[0] for r in rows)


def _zone_index(
    lon: float, lat: float, min_lon: float, max_lon: float, min_lat: float, max_lat: float
) -> int:
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat
    col = (
        min(ZONE_GRID_COLS - 1, max(0, int((lon - min_lon) / lon_span * ZONE_GRID_COLS)))
        if lon_span
        else 0
    )
    row = (
        min(ZONE_GRID_ROWS - 1, max(0, int((lat - min_lat) / lat_span * ZONE_GRID_ROWS)))
        if lat_span
        else 0
    )
    return row * ZONE_GRID_COLS + col


def compute_zone_profitability(
    snapshot: FarmSnapshot, canonical_id: str, season: int
) -> ZoneProfitabilityResult:
    lineage = snapshot.identity.lineages.get(canonical_id)
    if lineage is None or season not in lineage.active_seasons:
        raise ZoneProfitabilityUnavailable(f"{canonical_id} has no record for season {season}")

    covered_seasons = _as_applied_covered_seasons(snapshot)
    if season not in covered_seasons:
        raise ZoneProfitabilityUnavailable(
            "zone-level profitability is only available for seasons with as-applied "
            f"coverage: {covered_seasons}"
        )

    record = snapshot.profit_records.get((canonical_id, season))
    if record is None:
        raise ZoneProfitabilityUnavailable(f"no profit record for {canonical_id} in {season}")

    display_name = lineage.display_name_by_season[season]
    bbox = snapshot.con.execute(
        "SELECT min_lon, max_lon, min_lat, max_lat FROM boundary_fields "
        "WHERE field_name = ? AND season = ?",
        [display_name, season],
    ).fetchone()
    if bbox is None:
        raise ZoneProfitabilityUnavailable(f"no boundary geometry for {canonical_id} in {season}")
    min_lon, max_lon, min_lat, max_lat = bbox

    price_row = snapshot.con.execute(
        "SELECT AVG(price_per_bu) FROM scale_ticket_loads WHERE field_name = ? AND season = ?",
        [display_name, season],
    ).fetchone()
    price_per_bu = price_row[0] if price_row else None
    if price_per_bu is None:
        raise ZoneProfitabilityUnavailable(
            f"no scale ticket price data for {canonical_id} in {season}"
        )

    zone_acres = record.acres / ZONE_COUNT
    cost_per_acre = record.total_cost / record.acres if record.acres else 0.0

    points = snapshot.con.execute(
        "SELECT lon, lat, dry_bu_ac FROM yield_monitor_points WHERE field_name = ? AND season = ?",
        [display_name, season],
    ).fetchall()

    points_by_zone: dict[int, list[float]] = {i: [] for i in range(ZONE_COUNT)}
    for lon, lat, dry_bu_ac in points:
        points_by_zone[_zone_index(lon, lat, min_lon, max_lon, min_lat, max_lat)].append(
            dry_bu_ac
        )

    zones = []
    for idx in range(ZONE_COUNT):
        vals = points_by_zone[idx]
        if len(vals) < ZONE_MIN_POINTS:
            zones.append(
                ZoneProfitEntry(
                    zone_index=idx,
                    acres=round(zone_acres, 2),
                    available=False,
                    point_count=len(vals),
                    unavailable_reason="insufficient_coverage",
                )
            )
            continue
        yield_bu_ac = sum(vals) / len(vals)
        revenue = yield_bu_ac * zone_acres * price_per_bu
        cost = cost_per_acre * zone_acres
        zones.append(
            ZoneProfitEntry(
                zone_index=idx,
                acres=round(zone_acres, 2),
                available=True,
                point_count=len(vals),
                yield_bu_ac=round(yield_bu_ac, 2),
                revenue=round(revenue, 2),
                cost=round(cost, 2),
                profit=round(revenue - cost, 2),
            )
        )

    return ZoneProfitabilityResult(
        canonical_id=canonical_id,
        season=season,
        field_acres=record.acres,
        field_profit=record.profit,
        zones=zones,
    )


def unprofitable_zones_in_profitable_fields(snapshot: FarmSnapshot) -> dict[str, Any]:
    """The headline figure: of the acres in fields that were genuinely
    profitable overall that season, what fraction sat in a zone with
    negative zone-level profit. Only seasons with as-applied coverage are
    examined; zones without enough point coverage to compute are excluded
    from both the numerator and the denominator, not treated as zero.
    """
    covered_seasons = _as_applied_covered_seasons(snapshot)
    acres_examined = 0.0
    acres_unprofitable = 0.0
    field_seasons_examined = 0

    for (canonical_id, season), record in snapshot.profit_records.items():
        if season not in covered_seasons or record.profit <= 0:
            continue
        try:
            result = compute_zone_profitability(snapshot, canonical_id, season)
        except ZoneProfitabilityUnavailable:
            continue
        field_seasons_examined += 1
        for zone in result.zones:
            if not zone.available:
                continue
            acres_examined += zone.acres
            if zone.profit is not None and zone.profit < 0:
                acres_unprofitable += zone.acres

    pct = round(acres_unprofitable / acres_examined, 4) if acres_examined else None
    return {
        "seasons_examined": covered_seasons,
        "field_seasons_examined": field_seasons_examined,
        "acres_examined": round(acres_examined, 1),
        "acres_unprofitable": round(acres_unprofitable, 1),
        "pct_acres_unprofitable_in_profitable_fields": pct,
    }
