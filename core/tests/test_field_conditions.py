"""Weather, soil and as-applied lookups (farm_core.field_conditions): the
figures the weather-history and as-applied servers hand to the narrator.
Checked against the raw generated files and ground_truth.json, not against
the module's own arithmetic.
"""

import csv
from pathlib import Path

import pytest

from farm_core import field_conditions as fc
from farm_core.reconciliation import UAN32_LB_N_PER_GAL

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def _raw_precip() -> dict[int, float]:
    totals = {}
    for path in sorted((DATA_DIR / "weather").glob("weather_*.csv")):
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        totals[int(rows[0]["season"])] = sum(float(r["precip_mm"]) for r in rows)
    return totals


def test_forced_drought_season_is_the_driest_on_record(farm_snapshot, ground_truth):
    season = ground_truth["weathershortfall"]["season"]
    w = fc.season_weather_summary(farm_snapshot, season)
    raw = _raw_precip()
    assert w["total_precip_mm"] == round(raw[season], 1)
    assert w["farm_average_precip_mm"] == round(sum(raw.values()) / len(raw), 1)
    assert w["num_seasons_compared"] == len(raw)
    assert w["precip_rank_driest"] == 1
    assert w["pct_vs_farm_average"] < 0
    assert w["precip_short_of_need_mm"] == round(w["crop_water_need_mm"] - w["total_precip_mm"], 1)


def test_wettest_season_ranks_last(farm_snapshot):
    raw = _raw_precip()
    wettest = max(raw, key=raw.get)
    w = fc.season_weather_summary(farm_snapshot, wettest)
    assert w["precip_rank_driest"] == len(raw)
    assert w["precip_short_of_need_mm"] == 0.0


def test_unknown_season_is_a_refusal(farm_snapshot):
    with pytest.raises(fc.LookupRefused) as e:
        fc.season_weather_summary(farm_snapshot, 1999)
    assert e.value.code == "invalid_input"


def test_field_soil_and_farm_range(farm_snapshot):
    with (DATA_DIR / "weather" / "soil_awc.csv").open(newline="") as f:
        awc = {r["field_name"]: float(r["awc_in"]) for r in csv.DictReader(f)}
    s = fc.field_soil_summary(farm_snapshot, "Coulee Field")
    assert s["awc_in"] == awc["Coulee Field"]
    assert s["farm_min_awc_in"] <= s["awc_in"] <= s["farm_max_awc_in"]
    assert awc[s["min_field_name"]] == s["farm_min_awc_in"]
    assert awc[s["max_field_name"]] == s["farm_max_awc_in"]


def test_field_soil_resolves_a_renamed_field(farm_snapshot, ground_truth):
    renamed = next(e for e in ground_truth["identity_events"] if e["type"] == "rename")
    names = ground_truth["canonical_fields"][renamed["field_id"]]["display_name_by_season"]
    old = names[min(names, key=int)]
    new = names[max(names, key=int)]
    s = fc.field_soil_summary(farm_snapshot, old)
    assert s["asked_name"] == old
    assert s["field_name"] == new


def test_unknown_field_soil_is_a_refusal(farm_snapshot):
    with pytest.raises(fc.LookupRefused) as e:
        fc.field_soil_summary(farm_snapshot, "No Such Field")
    assert e.value.code == "not_found"


def _uan_season(ground_truth) -> int:
    return min(
        d["season"]
        for d in ground_truth["defects"]
        if d["type"] == "unit_inconsistency" and "gal/ac" in d["detail"]
    )


def test_applied_inputs_convert_uan_gallons_to_lb_n(farm_snapshot, ground_truth):
    season = _uan_season(ground_truth)
    a = fc.applied_inputs(farm_snapshot, "Coulee Field", season)
    n = next(e for e in a["applied_inputs"] if e["input"] == "nitrogen")
    assert n["as_logged_unit"] == "gal/ac"
    assert n["converted"] is True
    assert n["unit"] == "lb N/ac"
    assert n["rate"] == round(n["as_logged_rate"] * UAN32_LB_N_PER_GAL, 1)
    assert a["nitrogen_lb_n_ac"] == n["rate"]
    assert [e["input"] for e in a["applied_inputs"]] == [
        "seed", "nitrogen", "phosphorus", "potassium", "herbicide"
    ]
    assert a["crop"] == ground_truth["canonical_fields"]["root_11"]["crop_by_season"][str(season)]


def test_applied_inputs_before_logs_start_is_empty_not_an_error(farm_snapshot):
    a = fc.applied_inputs(farm_snapshot, "Coulee Field", 2019)
    assert a["logged"] is False
    assert a["applied_inputs"] == []
    assert a["nitrogen_lb_n_ac"] is None
    assert 2019 not in a["logged_seasons"]


def test_applied_inputs_for_a_field_that_did_not_exist_that_season(farm_snapshot):
    with pytest.raises(fc.LookupRefused) as e:
        fc.applied_inputs(farm_snapshot, "Elevator Forty", 2023)  # merged after 2021
    assert e.value.code == "not_found"


def test_nitrogen_history_groups_by_crop(farm_snapshot, ground_truth):
    h = fc.nitrogen_history(farm_snapshot, "Section Corner")
    seasons = [r["season"] for r in h["nitrogen_by_season"]]
    assert seasons == sorted(seasons) and h["logs_start_season"] == seasons[0]
    for crop, c in h["nitrogen_by_crop"].items():
        rates = [r["n_lb_n_ac"] for r in h["nitrogen_by_season"] if r["crop"] == crop]
        assert c["min_lb_n_ac"] == min(rates)
        assert c["max_lb_n_ac"] == max(rates)
        assert c["spread_lb_n_ac"] == round(max(rates) - min(rates), 1)
    # Every gal/ac season is converted; lb N/ac seasons pass through.
    for r in h["nitrogen_by_season"]:
        expected = r["as_logged_rate"] * (UAN32_LB_N_PER_GAL if r["converted"] else 1)
        assert r["n_lb_n_ac"] == round(expected, 1)
        assert r["converted"] == (r["as_logged_unit"] == "gal/ac")
