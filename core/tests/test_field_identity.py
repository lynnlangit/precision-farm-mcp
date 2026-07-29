"""Phase 1 verification: field identity resolved from raw boundary files alone
must exactly match the generator's ground truth -- the whole point of Phase 1
is that this is provable without any shortcut into the generator's internals.
"""

import json
from pathlib import Path

import pytest

from farm_core import alias_resolution, confirm, db, field_identity, ingest_boundaries
from farm_core import ingest_cost_ledger_names

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
SEASONS = list(range(2016, 2026))


def _ground_truth_field_name(gt: dict, field_id: str) -> str:
    names = gt["canonical_fields"][field_id]["display_name_by_season"].values()
    unique = set(names)
    assert len(unique) == 1, f"expected a stable name for {field_id}, got {unique}"
    return next(iter(unique))


@pytest.fixture(scope="module")
def ground_truth() -> dict:
    return json.loads((DATA_DIR / "ground_truth.json").read_text())


@pytest.fixture(scope="module")
def resolution():
    con = db.connect()
    ingest_boundaries.ingest_boundaries(con, DATA_DIR)
    ingest_cost_ledger_names.ingest_cost_ledger_field_names(con, DATA_DIR)
    result = field_identity.resolve_field_identity(con, SEASONS, confirm.auto_approve)
    aliases = alias_resolution.resolve_all_aliases(con, SEASONS, confirm.auto_approve)
    return result, aliases


def _names(ground_truth: dict, field_ids: list[str]) -> tuple:
    return tuple(sorted(_ground_truth_field_name(ground_truth, fid) for fid in field_ids))


def _expected_events_by_name(ground_truth: dict) -> list[dict]:
    expected = []
    for event in ground_truth["identity_events"]:
        if event["type"] == "rename":
            expected.append(
                {
                    "type": "rename",
                    "effective_season": event["effective_season"],
                    "old_name": event["old_name"],
                    "new_name": event["new_name"],
                }
            )
        elif event["type"] in ("split", "merge"):
            expected.append(
                {
                    "type": event["type"],
                    "effective_season": event["effective_season"],
                    "parent_names": _names(ground_truth, event["parent_field_ids"]),
                    "child_names": _names(ground_truth, event["child_field_ids"]),
                }
            )
        elif event["type"] == "rental_lost":
            expected.append(
                {
                    "type": "rental_lost",
                    "effective_season": event["effective_season"],
                    "old_name": _ground_truth_field_name(ground_truth, event["field_id"]),
                    "last_season_present": event["last_season_present"],
                }
            )
    return expected


def test_identity_event_count_matches(resolution, ground_truth):
    result, _ = resolution
    assert len(result.events) == len(ground_truth["identity_events"])


def test_every_identity_event_matches_ground_truth(resolution, ground_truth):
    result, _ = resolution
    expected = _expected_events_by_name(ground_truth)

    resolved_by_type: dict[str, list] = {}
    for e in result.events:
        resolved_by_type.setdefault(e.type, []).append(e)

    for exp in expected:
        matches = [
            e
            for e in resolved_by_type.get(exp["type"], [])
            if e.effective_season == exp["effective_season"]
        ]
        assert matches, f"no resolved {exp['type']} event at season {exp['effective_season']}"
        e = matches[0]

        if exp["type"] == "rename":
            assert e.old_name == exp["old_name"]
            assert e.new_name == exp["new_name"]
        elif exp["type"] in ("split", "merge"):
            assert tuple(sorted(e.parent_names)) == exp["parent_names"]
            assert tuple(sorted(e.child_names)) == exp["child_names"]
        elif exp["type"] == "rental_lost":
            assert e.old_name == exp["old_name"]
            assert e.last_season_present == exp["last_season_present"]


def test_lineage_count_matches_expected_structure(resolution):
    result, _ = resolution
    # 12 root fields + 2 split children + 1 merge child = 15 lineages ever created
    assert len(result.lineages) == 15


def test_active_field_names_match_ground_truth_per_season(resolution, ground_truth):
    result, _ = resolution
    gt_fields = ground_truth["canonical_fields"]

    for season in SEASONS:
        resolved_names = {
            lineage.display_name_by_season[season]
            for lineage in result.lineages.values()
            if season in lineage.display_name_by_season
        }
        gt_names = {
            info["display_name_by_season"][str(season)]
            for info in gt_fields.values()
            if str(season) in info["display_name_by_season"]
        }
        assert resolved_names == gt_names, f"mismatch in season {season}"


def test_naming_drift_field_resolves_to_stable_canonical_name(resolution):
    _, aliases = resolution
    variants = ["N 80", "north eighty", "North 80", "N80"]
    resolved_targets = {a.canonical_boundary_name for a in aliases if a.raw_field_name in variants}
    assert resolved_targets == {"N 80"}


def test_no_naming_drift_confusion_with_similarly_named_fields(resolution):
    """Regression guard: 'Marginal Eighty' shares the literal word 'eighty'
    with the drift variant 'north eighty' -- string similarity alone would
    risk matching them. Acreage-based resolution must not conflate them.
    """
    _, aliases = resolution
    for a in aliases:
        if a.raw_field_name == "north eighty":
            assert a.canonical_boundary_name == "N 80"
            assert a.canonical_boundary_name != "Marginal Eighty"
