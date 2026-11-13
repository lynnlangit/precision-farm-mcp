"""Template answers and the units check for the weather, soil and
as-applied question types. No model call: template_answer and the checks
are plain code, so these run anywhere.
"""

from farm_model.narrator import template_answer
from farm_model.verification import (
    check_narration_grounded,
    check_units_consistent,
    failed_semantic_checks,
)

WEATHER = {
    "season": 2018,
    "total_precip_mm": 172.6,
    "farm_average_precip_mm": 434.4,
    "pct_vs_farm_average": -60,
    "num_seasons_compared": 10,
    "precip_rank_driest": 1,
    "crop_water_need_mm": 450.0,
    "precip_short_of_need_mm": 277.4,
    "heat_stress_days": 82,
    "farm_average_heat_stress_days": 80.6,
    "heat_stress_threshold_c": 32.0,
}

SOIL = {
    "field_name": "Sheyenne Bottom",
    "asked_name": "River Bottom",
    "awc_in": 8.93,
    "farm_min_awc_in": 4.08,
    "min_field_name": "West 120",
    "farm_max_awc_in": 8.93,
    "max_field_name": "Sheyenne Bottom",
    "num_current_fields": 11,
}


def _input(kind, product, rate, unit, logged_rate=None, logged_unit=None):
    return {
        "input": kind,
        "product": product,
        "rate": rate,
        "unit": unit,
        "as_logged_rate": logged_rate if logged_rate is not None else rate,
        "as_logged_unit": logged_unit or unit,
        "converted": logged_unit == "gal/ac",
    }


APPLIED = {
    "field_name": "Coulee Field",
    "asked_name": "Coulee Field",
    "season": 2023,
    "crop": "corn",
    "logged": True,
    "logged_seasons": [2022, 2023, 2024, 2025],
    "applied_inputs": [
        _input("seed", "Seed - Corn Hybrid", 35.7, "kseeds/ac"),
        _input("nitrogen", "UAN 32% (32-0-0)", 145.9, "lb N/ac", 41.22, "gal/ac"),
        _input("phosphorus", "MAP (11-52-0)", 53.1, "lb P2O5/ac", 53.1, "lb_P2O5/ac"),
        _input("potassium", "Potash (0-0-60)", 56.8, "lb K2O/ac", 56.8, "lb_K2O/ac"),
        _input("herbicide", "Glyphosate + Residual Herbicide", 2.52, "qt/ac"),
    ],
    "nitrogen_lb_n_ac": 145.9,
    "uan32_lb_n_per_gal": 3.5392,
}

HISTORY = {
    "field_name": "Section Corner",
    "asked_name": "Section Corner",
    "nitrogen_by_season": [
        {"season": 2022, "field_name": "Section Corner", "crop": "soybean", "product": "Anhydrous Ammonia (82-0-0)", "n_lb_n_ac": 5.2,
         "as_logged_rate": 5.2, "as_logged_unit": "lb_N/ac", "converted": False},
        {"season": 2023, "field_name": "Section Corner", "crop": "corn", "product": "UAN 32% (32-0-0)", "n_lb_n_ac": 160.6,
         "as_logged_rate": 45.38, "as_logged_unit": "gal/ac", "converted": True},
        {"season": 2024, "field_name": "Section Corner", "crop": "soybean", "product": "Anhydrous Ammonia (82-0-0)", "n_lb_n_ac": 6.2,
         "as_logged_rate": 6.2, "as_logged_unit": "lb_N/ac", "converted": False},
        {"season": 2025, "field_name": "Section Corner", "crop": "corn", "product": "UAN 32% (32-0-0)", "n_lb_n_ac": 141.3,
         "as_logged_rate": 39.92, "as_logged_unit": "gal/ac", "converted": True},
    ],
    "nitrogen_by_crop": {
        "corn": {"num_seasons": 2, "min_lb_n_ac": 141.3, "min_season": 2025,
                 "max_lb_n_ac": 160.6, "max_season": 2023, "spread_lb_n_ac": 19.3},
        "soybean": {"num_seasons": 2, "min_lb_n_ac": 5.2, "min_season": 2022,
                    "max_lb_n_ac": 6.2, "max_season": 2024, "spread_lb_n_ac": 1.0},
    },
    "logs_start_season": 2022,
    "uan32_lb_n_per_gal": 3.5392,
}


def _assert_lead_passes(payload, question):
    lead = template_answer(question, payload)
    assert check_narration_grounded(lead, payload, question=question).is_grounded, lead
    assert failed_semantic_checks(lead, payload) == [], lead
    return lead


def test_weather_lead():
    lead = _assert_lead_passes(WEATHER, "How dry was 2018?")
    assert "172.6 mm" in lead
    assert "60% below the 10-season farm average of 434.4 mm" in lead
    assert "driest of the 10 seasons" in lead
    assert "277.4 mm short of the 450 mm" in lead
    assert "82 days topped 32 °C" in lead


def test_weather_lead_for_a_wet_season():
    wet = {**WEATHER, "season": 2025, "total_precip_mm": 632.5, "pct_vs_farm_average": 46,
           "precip_rank_driest": 10, "precip_short_of_need_mm": 0.0}
    lead = _assert_lead_passes(wet, "How wet was 2025?")
    assert "46% above" in lead and "wettest" in lead and "covers the 450 mm" in lead


def test_soil_lead_names_the_rename_and_the_range():
    lead = _assert_lead_passes(SOIL, "How much water does River Bottom's soil hold?")
    assert lead.startswith("“River Bottom” is recorded as Sheyenne Bottom.")
    assert "8.93 inches" in lead and "the most of any current field" in lead
    assert "4.08 in (West 120)" in lead


def test_applied_inputs_lead_shows_lb_n_and_the_conversion():
    lead = _assert_lead_passes(APPLIED, "What did I put on Coulee Field in 2023?")
    assert "nitrogen at 145.9 lb N/ac" in lead
    assert "logged as 41.22 gal/ac of UAN 32%, converted at 3.5392 lb N per gallon" in lead


def test_applied_inputs_before_logs_start():
    payload = {**APPLIED, "season": 2019, "logged": False, "applied_inputs": [],
               "nitrogen_lb_n_ac": None}
    lead = _assert_lead_passes(payload, "What did I put on Coulee Field in 2019?")
    assert "no as-applied log for Coulee Field in 2019" in lead
    assert "2022-2025 only" in lead


def test_nitrogen_history_lead_keeps_crops_apart():
    lead = _assert_lead_passes(HISTORY, "Did I put the same nitrogen on Section Corner every year?")
    assert "2023 corn 160.6 (logged as 45.38 gal/ac" in lead
    assert "In corn years it ranged from 141.3 (2025) to 160.6 (2023), a spread of 19.3" in lead
    assert "In soybean years it ranged from 5.2 (2022) to 6.2 (2024)" in lead
    assert "no as-applied log before 2022" in lead


# -- the units check ---------------------------------------------------------


def test_units_check_catches_gallons_read_as_pounds():
    bad = "Coulee Field got only 41.22 lb of nitrogen in 2023."
    assert not check_units_consistent(bad, APPLIED)
    assert "units" in failed_semantic_checks(bad, APPLIED)
    # The same number with its real unit passes.
    assert check_units_consistent("The log shows 41.22 gal/ac of UAN 32%.", APPLIED)


def test_units_check_catches_soil_inches_read_as_rain():
    assert not check_units_consistent("Sheyenne Bottom got 8.93 mm of water.", SOIL)
    assert check_units_consistent("Sheyenne Bottom's soil holds 8.93 inches.", SOIL)


def test_units_check_catches_rain_in_the_wrong_unit():
    assert not check_units_consistent("2018 had 172.6 inches of rain.", WEATHER)
    assert check_units_consistent("2018 had about 173 mm of rain.", WEATHER)


def test_units_check_ignores_years_after_in():
    assert check_units_consistent("Nitrogen rose to 160.6 in 2023.", HISTORY)


def test_units_check_leaves_other_payloads_alone():
    assert check_units_consistent("It lost 12 lb of something.", {"verdict": "bad_year"})
