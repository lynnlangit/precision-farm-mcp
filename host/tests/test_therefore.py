"""The "therefore" line (item 7): deterministic, never model-generated, and
omitted rather than invented whenever a payload doesn't carry a claim worth
restating.
"""

from farm_host.therefore import build_therefore_line


def test_bad_field_verdict_restates_the_loss_pattern():
    payload = {
        "verdict": "bad_field",
        "evidence": {"loss_rate": 0.6, "num_seasons": 5, "seasons_with_loss": [2020, 2021]},
    }
    line = build_therefore_line(payload)
    assert line is not None
    assert line.startswith("Therefore:")
    assert "60%" in line


def test_bad_year_verdict_names_the_outlier_seasons():
    payload = {
        "verdict": "bad_year",
        "evidence": {"outlier_seasons": [2018], "median_profit_per_acre": 62.81, "num_seasons": 10},
    }
    line = build_therefore_line(payload)
    assert line is not None
    assert "2018" in line


def test_consistently_profitable_verdict_has_a_line():
    payload = {"verdict": "consistently_profitable", "evidence": {}}
    assert build_therefore_line(payload) is not None


def test_no_data_verdict_is_omitted_not_invented():
    payload = {"canonical_id": "root_01", "verdict": "no_data", "evidence": {}}
    assert build_therefore_line(payload) is None


def test_zone_profitability_with_an_unprofitable_zone():
    payload = {
        "canonical_id": "root_12",
        "season": 2024,
        "field_acres": 125.8,
        "field_profit": 5893.80,
        "zones": [
            {"zone_index": 0, "available": True, "profit": -120.0},
            {"zone_index": 1, "available": True, "profit": 300.0},
            {"zone_index": 2, "available": True, "profit": 200.0},
            {"zone_index": 3, "available": True, "profit": 150.0},
        ],
    }
    line = build_therefore_line(payload)
    assert line is not None
    assert "1 of 4" in line


def test_zone_profitability_with_no_unprofitable_zone():
    payload = {
        "field_profit": 5893.80,
        "zones": [
            {"zone_index": 0, "available": True, "profit": 100.0},
            {"zone_index": 1, "available": True, "profit": 300.0},
        ],
    }
    line = build_therefore_line(payload)
    assert line is not None
    assert "no measurable zone" in line.lower()


def test_zone_profitability_field_itself_unprofitable():
    payload = {
        "field_profit": -500.0,
        "zones": [{"zone_index": 0, "available": True, "profit": -100.0}],
    }
    line = build_therefore_line(payload)
    assert "overall" in line.lower()


def test_zone_profitability_with_no_available_zones_is_omitted():
    payload = {
        "field_profit": 100.0,
        "zones": [{"zone_index": 0, "available": False, "profit": None}],
    }
    assert build_therefore_line(payload) is None


def test_unprofitable_zones_summary_with_data():
    payload = {
        "seasons_examined": [2024, 2025],
        "field_seasons_examined": 3,
        "acres_examined": 200.0,
        "acres_unprofitable": 40.0,
        "pct_acres_unprofitable_in_profitable_fields": 0.2,
    }
    line = build_therefore_line(payload)
    assert line is not None
    assert "20.0%" in line


def test_unprofitable_zones_summary_with_no_examinable_acres_is_omitted():
    payload = {
        "seasons_examined": [],
        "field_seasons_examined": 0,
        "acres_examined": 0.0,
        "acres_unprofitable": 0.0,
        "pct_acres_unprofitable_in_profitable_fields": None,
    }
    assert build_therefore_line(payload) is None


def test_which_fields_made_money_names_the_top_field():
    payload = {
        "results": [
            {"canonical_id": "root_01", "display_name": "North Eighty", "total_profit": 5000.0},
            {"canonical_id": "root_02", "display_name": "South Forty", "total_profit": 2000.0},
        ]
    }
    line = build_therefore_line(payload)
    assert line is not None
    assert "North Eighty" in line


def test_empty_ranking_results_is_omitted():
    assert build_therefore_line({"results": []}) is None


def test_reconciliation_and_resolve_field_name_shapes_are_omitted():
    """No verdict, no zones, no ranking -- restating anything here would be
    inventing a claim the computation never made.
    """
    assert build_therefore_line({"canonical_id": "root_01", "matches": True}) is None
    assert build_therefore_line({"raw_name": "north 8", "resolved_to": "North Eighty"}) is None
