"""Phase D verification: zone-level profitability. Grid-index math is pure
and tested standalone; the refusal paths are tested against a small
hand-built FarmSnapshot fixture (no need for the full synthetic dataset just
to prove a season-coverage or point-count refusal); the actual defect
(DEF-BADZONE) and the headline summary are tested against the real
`farm_snapshot` fixture, since they need genuine yield-monitor point data.
"""

import dataclasses
from pathlib import Path

import pytest

from farm_core import db, zone_profitability as zp
from farm_core.field_identity import FieldIdentityResolution, Lineage
from farm_core.pipeline import FarmSnapshot
from farm_core.profitability import ProfitRecord


# --- pure grid math, no DB needed ---


@pytest.mark.parametrize(
    "lon,lat,expected_zone",
    [
        (0.25, 0.25, 0),  # bottom-left quadrant
        (0.75, 0.25, 1),  # bottom-right
        (0.25, 0.75, 2),  # top-left
        (0.75, 0.75, 3),  # top-right
        (0.0, 0.0, 0),  # exact min corner -> zone 0
        (1.0, 1.0, 3),  # exact max corner -> zone 3, not out of range
    ],
)
def test_zone_index_quadrants(lon, lat, expected_zone):
    assert zp._zone_index(lon, lat, 0.0, 1.0, 0.0, 1.0) == expected_zone


def test_zone_index_handles_a_degenerate_bbox():
    # A field with zero lon or lat span shouldn't divide by zero.
    assert zp._zone_index(0.5, 0.5, 0.5, 0.5, 0.0, 1.0) == 2
    assert zp._zone_index(0.5, 0.5, 0.0, 1.0, 0.5, 0.5) == 1


# --- refusal paths, hand-built minimal snapshot ---


def _minimal_snapshot(tmp_path: Path, *, with_as_applied: bool, point_count: int) -> FarmSnapshot:
    con = db.connect()
    con.execute(
        "INSERT INTO boundary_fields VALUES (2024, 'Test Field', 100.0, 'corn', "
        "0.0, 1.0, 0.0, 1.0, 'EPSG:4326', 'boundaries.geojson')"
    )
    con.execute(
        "INSERT INTO scale_ticket_loads VALUES "
        "(2024, 1, '2024-10-01', 'Test Field', 'corn', 1, 15.0, 1000.0, 950.0, 4.5, "
        "'Test Elevator', 'scale.csv')"
    )
    if with_as_applied:
        con.execute(
            "INSERT INTO as_applied_events VALUES "
            "(2024, 'Test Field', '2024-05-01', 'Seed - Corn Hybrid', 33.0, 'kseeds/ac', "
            "0.5, 0.5, 'as_applied.csv')"
        )
    for i in range(point_count):
        # All points in zone 0 (bottom-left quadrant) for this fixture.
        con.execute(
            "INSERT INTO yield_monitor_points VALUES "
            "('Test Field', 2024, ?, 0.1, 0.1, 150.0, 145.0, 15.0, 'monitor.csv')",
            [f"2024-10-01T0{i % 6}:00:00"],
        )

    lineage = Lineage(
        canonical_id="cid_1",
        display_name_by_season={2024: "Test Field"},
        active_seasons=[2024],
    )
    identity = FieldIdentityResolution(lineages={"cid_1": lineage}, events=[])
    record = ProfitRecord(
        canonical_id="cid_1",
        display_name="Test Field",
        season=2024,
        crop="corn",
        acres=100.0,
        revenue=4500.0,
        total_cost=3000.0,
        profit=1500.0,
        profit_per_acre=15.0,
    )
    return FarmSnapshot(
        con=con,
        identity=identity,
        alias_map={},
        profit_records={("cid_1", 2024): record},
        seasons=[2024],
        data_dir=tmp_path,
        built_at="2024-01-01T00:00:00Z",
        source_files=[],
    )


def test_refuses_for_a_season_with_no_as_applied_coverage(tmp_path):
    snap = _minimal_snapshot(tmp_path, with_as_applied=False, point_count=50)
    with pytest.raises(zp.ZoneProfitabilityUnavailable):
        zp.compute_zone_profitability(snap, "cid_1", 2024)


def test_refuses_for_an_unknown_canonical_id(tmp_path):
    snap = _minimal_snapshot(tmp_path, with_as_applied=True, point_count=50)
    with pytest.raises(zp.ZoneProfitabilityUnavailable):
        zp.compute_zone_profitability(snap, "not_a_real_field", 2024)


def test_zone_with_too_few_points_is_marked_unavailable_not_estimated(tmp_path):
    snap = _minimal_snapshot(tmp_path, with_as_applied=True, point_count=zp.ZONE_MIN_POINTS - 1)
    result = zp.compute_zone_profitability(snap, "cid_1", 2024)
    zone_0 = result.zones[0]
    assert zone_0.available is False
    assert zone_0.unavailable_reason == "insufficient_coverage"
    assert zone_0.profit is None
    # Sibling zones with zero points are unavailable too, not zero-profit.
    for zone in result.zones[1:]:
        assert zone.available is False


def test_zone_with_enough_points_computes_a_real_profit(tmp_path):
    snap = _minimal_snapshot(tmp_path, with_as_applied=True, point_count=zp.ZONE_MIN_POINTS + 5)
    result = zp.compute_zone_profitability(snap, "cid_1", 2024)
    zone_0 = result.zones[0]
    assert zone_0.available is True
    assert zone_0.point_count == zp.ZONE_MIN_POINTS + 5
    assert zone_0.yield_bu_ac == pytest.approx(145.0, abs=0.01)
    assert zone_0.acres == pytest.approx(25.0, abs=0.01)  # 100 acres / 4 zones
    # cost_per_acre = total_cost/acres = 3000/100 = 30; zone cost = 30 * 25 = 750
    assert zone_0.cost == pytest.approx(750.0, abs=0.01)


def test_field_level_profit_is_untouched_by_zone_computation(tmp_path):
    snap = _minimal_snapshot(tmp_path, with_as_applied=True, point_count=50)
    result = zp.compute_zone_profitability(snap, "cid_1", 2024)
    assert result.field_profit == 1500.0
    assert result.field_acres == 100.0


# --- the real defect and the headline summary, against real synthetic data ---


def test_def_badzone_shows_a_genuinely_negative_zone_inside_a_profitable_field(
    farm_snapshot, ground_truth
):
    bad_zone = ground_truth["bad_zone"]
    assert bad_zone is not None, "DEF-BADZONE should fire with the default 12-field roster"

    field = ground_truth["canonical_fields"][bad_zone["field_id"]]
    name = field["display_name_by_season"][str(bad_zone["season"])]
    canonical_id = farm_snapshot.canonical_id_for_name(name)

    result = zp.compute_zone_profitability(farm_snapshot, canonical_id, bad_zone["season"])
    target = result.zones[bad_zone["zone_index"]]

    assert target.available is True
    assert target.profit is not None and target.profit < 0
    # The field's own total profit is unaffected by the zone-level shortfall
    # -- ground truth's own profitability figure for this field/season.
    gt_profit = ground_truth["profitability"][bad_zone["field_id"]][str(bad_zone["season"])][
        "profit"
    ]
    assert result.field_profit == pytest.approx(gt_profit, rel=0.005)
    assert result.field_profit > 0

    other_zones = [z for i, z in enumerate(result.zones) if i != bad_zone["zone_index"]]
    assert all(z.profit is None or z.profit > target.profit for z in other_zones)


def test_unprofitable_zones_summary_has_a_consistent_denominator(farm_snapshot):
    summary = zp.unprofitable_zones_in_profitable_fields(farm_snapshot)
    assert summary["acres_examined"] >= summary["acres_unprofitable"] >= 0
    if summary["acres_examined"] > 0:
        assert summary["pct_acres_unprofitable_in_profitable_fields"] == pytest.approx(
            summary["acres_unprofitable"] / summary["acres_examined"], abs=0.0001
        )
    else:
        assert summary["pct_acres_unprofitable_in_profitable_fields"] is None
