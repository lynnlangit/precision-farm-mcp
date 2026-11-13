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
    line = build_therefore_line(payload)
    assert line is not None
    assert "no season" not in line  # without a count, never claim zero losses


def test_consistently_profitable_states_the_real_loss_count():
    """Eval 3: South 160 South lost money in 1 of 6 seasons -- the line must
    say so, not "no season shows a loss pattern".
    """
    payload = {
        "verdict": "consistently_profitable",
        "evidence": {
            "median_profit_per_acre": 175.41,
            "loss_rate": 0.17,
            "num_seasons": 6,
            "num_loss_seasons": 1,
        },
    }
    line = build_therefore_line(payload)
    assert line == (
        "Therefore: this field lost money in 1 of 6 recorded seasons (median $175.41/ac) "
        "-- neither a chronic pattern nor a single standout bad year."
    )


def test_consistently_profitable_with_zero_losses():
    payload = {
        "verdict": "consistently_profitable",
        "evidence": {"median_profit_per_acre": 1234.5, "num_seasons": 10, "num_loss_seasons": 0},
    }
    line = build_therefore_line(payload)
    assert line == (
        "Therefore: this field lost money in none of its 10 recorded seasons "
        "(median $1,234.50/ac)."
    )


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


def test_which_fields_made_money_counts_and_names_top_and_bottom():
    """Evals 4-5: the line must say how many fields made money and name the
    lowest field, with a negative total shown as a loss.
    """
    payload = {
        "results": [
            {"display_name": "East 80", "seasons": [2021, 2022, 2023, 2024, 2025],
             "total_profit": 135533.57},
            {"display_name": "Home Quarter", "seasons": [2021, 2022, 2023, 2024, 2025],
             "total_profit": 1000.0},
            {"display_name": "Marginal Eighty", "seasons": [2021, 2022, 2023, 2024, 2025],
             "total_profit": -112044.66},
        ],
        "num_fields": 3,
        "num_fields_made_money": 2,
    }
    assert build_therefore_line(payload) == (
        "Therefore: 2 of 3 fields made money over 2021-2025; East 80 ranked highest "
        "($135,533.57), Marginal Eighty lowest (-$112,044.66)."
    )


def test_which_fields_made_money_non_consecutive_seasons_and_old_payload():
    payload = {
        "results": [
            {"display_name": "A", "seasons": [2019, 2021], "total_profit": 10.0},
            {"display_name": "B", "seasons": [2019], "total_profit": -5.0},
        ]
    }
    line = build_therefore_line(payload)
    assert "1 of 2 fields made money over 2019 and 2021" in line
    assert "B lowest (-$5.00)" in line


def test_empty_ranking_results_is_omitted():
    assert build_therefore_line({"results": []}) is None


def test_reconciliation_and_resolve_field_name_shapes_are_omitted():
    """No verdict, no zones, no ranking -- restating anything here would be
    inventing a claim the computation never made.
    """
    assert build_therefore_line({"canonical_id": "root_01", "matches": True}) is None
    assert build_therefore_line({"raw_name": "north 8", "resolved_to": "North Eighty"}) is None


def test_cost_reconciliation_results_get_no_ranking_line():
    """Eval 9 printed "0 of 2 fields made money ... ($0.00)" because its line
    items also live under "results". Cost reconciliation has no verdict to restate."""
    payload = {
        "results": [
            {"field_name": "Riverside", "season": 2022, "line_item": "seed",
             "ledger_cost_per_ac": 95.55, "outlier_flagged": True},
            {"field_name": "Riverside", "season": 2022, "line_item": "fertilizer",
             "ledger_cost_per_ac": 134.31, "outlier_flagged": False},
        ]
    }
    assert build_therefore_line(payload) is None
