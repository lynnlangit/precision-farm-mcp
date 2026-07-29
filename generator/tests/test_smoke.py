import json

import pytest

from farm_data_gen.cli import generate
from farm_data_gen.config import SimConfig

REQUIRED_DEFECT_TYPES = {
    "split",
    "merge",
    "rename",
    "rental_lost",
    "naming_drift",
    "yield_monitor_calibration_error",
    "missing_swath",
    "no_yield_monitor",
    "spreadsheet_merged_header",
    "spreadsheet_notes_column",
    "spreadsheet_totals_row_in_range",
    "spreadsheet_blank_rows",
    "cost_basis_total_dollars",
    "transposed_digit",
    "unit_inconsistency",
}


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("full_run")
    config = SimConfig(random_seed=42, num_fields=12, num_seasons=10)
    generate(config, out_dir)
    ground_truth = json.loads((out_dir / "ground_truth.json").read_text())
    return out_dir, config, ground_truth


def test_output_files_present(generated):
    out_dir, config, _ = generated
    for season in config.seasons:
        assert (out_dir / "boundaries" / f"field_boundaries_{season}.geojson").exists()
        assert (out_dir / "scale_tickets" / f"scale_tickets_{season}.csv").exists()
    assert (out_dir / "cost_ledger.xlsx").exists()
    assert (out_dir / "ground_truth.json").exists()
    assert (out_dir / "README.md").exists()

    monitor_files = list((out_dir / "yield_monitor").glob("*.csv"))
    assert len(monitor_files) > 0
    as_applied_files = list((out_dir / "as_applied").glob("*.csv"))
    assert len(as_applied_files) == 4  # last four seasons only


def test_every_required_defect_type_present(generated):
    _, _, ground_truth = generated
    present_types = {d["type"] for d in ground_truth["defects"]}
    missing = REQUIRED_DEFECT_TYPES - present_types
    assert not missing, f"missing required defect types: {missing}"


def test_defect_ids_are_unique(generated):
    _, _, ground_truth = generated
    ids = [d["defect_id"] for d in ground_truth["defects"]]
    assert len(ids) == len(set(ids))


def test_calibration_errors_both_directions(generated):
    _, _, ground_truth = generated
    cal_defects = [
        d for d in ground_truth["defects"] if d["type"] == "yield_monitor_calibration_error"
    ]
    assert len(cal_defects) == 4
    directions = {"+" if " +" in d["detail"] else "-" for d in cal_defects}
    assert directions == {"+", "-"}


def test_marginal_field_loses_money_most_seasons(generated):
    _, config, ground_truth = generated
    marginal_id = ground_truth["marginal_field_id"]
    seasons = ground_truth["profitability"][marginal_id]
    losses = sum(1 for v in seasons.values() if v["profit"] < 0)
    assert losses >= (len(seasons) // 2) + 1, "marginal field should lose money most seasons"


def test_catastrophic_year_is_a_true_outlier(generated):
    _, _, ground_truth = generated
    cat = ground_truth["catastrophic_year"]
    field_id, season = cat["field_id"], cat["season"]
    seasons = ground_truth["profitability"][field_id]
    cat_profit = seasons[str(season)]["profit"]
    other_profits = [v["profit"] for s, v in seasons.items() if int(s) != season]
    assert cat_profit < min(other_profits), "catastrophic season should be the field's worst by far"


def test_split_and_merge_acreage_conserved(generated):
    _, _, ground_truth = generated
    fields = ground_truth["canonical_fields"]
    for event in ground_truth["identity_events"]:
        if event["type"] == "split":
            (parent,) = event["parent_field_ids"]
            parent_seasons = fields[parent]["acres_by_season"]
            parent_acres = next(iter(parent_seasons.values()))
            child_total = sum(
                next(iter(fields[c]["acres_by_season"].values())) for c in event["child_field_ids"]
            )
            assert abs(parent_acres - child_total) < 0.1
        elif event["type"] == "merge":
            parent_total = sum(
                next(iter(fields[p]["acres_by_season"].values())) for p in event["parent_field_ids"]
            )
            (child,) = event["child_field_ids"]
            child_acres = next(iter(fields[child]["acres_by_season"].values()))
            assert abs(parent_total - child_acres) < 0.1


def test_scale_ticket_totals_match_true_yield(generated):
    """Scale tickets are the authoritative bushel source: their per-field sum
    must equal true yield_bu_ac * acres (from the same in-memory model the
    ground truth is built from), to within ordinary load-rounding noise -- the
    non-defect baseline that the calibration-error defect deliberately breaks
    on the yield *monitor* side only.
    """
    import csv

    from farm_data_gen.farm import build_farm

    out_dir, config, _ground_truth = generated
    farm = build_farm(config)
    season = config.seasons[0]

    with open(out_dir / "scale_tickets" / f"scale_tickets_{season}.csv") as f:
        rows = list(csv.DictReader(f))

    totals_by_field: dict[str, float] = {}
    for row in rows:
        totals_by_field.setdefault(row["field_name"], 0.0)
        totals_by_field[row["field_name"]] += float(row["net_bushels"])

    for field_id in farm.fields_active_in(season):
        name = farm.display_name(field_id, season)
        record = farm.record(field_id, season)
        true_total = record.yield_bu_ac * record.acres
        assert totals_by_field[name] == pytest.approx(true_total, rel=0.001)
