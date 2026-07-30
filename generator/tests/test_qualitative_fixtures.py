"""Phase C2: causal weather/soil yield changed every profit number, but the
qualitative *stories* the eval questions and README depend on must survive
regeneration unchanged -- same stories, new numbers. Each test here mirrors
the exact classification logic the query-time system uses
(farm_core.profitability.bad_field_or_bad_year's loss-rate and MAD-outlier
rules), reimplemented locally rather than imported, since the generator
package has no dependency on farm_core.
"""

import json
import statistics

import pytest

from farm_data_gen.cli import generate
from farm_data_gen.config import SimConfig

# Mirrors farm_core.profitability's thresholds exactly -- kept in sync by hand,
# not imported, to preserve the generator/core package boundary.
LOSS_RATE_BAD_FIELD_THRESHOLD = 0.5
OUTLIER_MAD_MULTIPLIER = 2.0


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("qual_fixtures")
    config = SimConfig(random_seed=42, num_fields=12, num_seasons=10)
    generate(config, out_dir)
    ground_truth = json.loads((out_dir / "ground_truth.json").read_text())
    return config, ground_truth


def _outlier_seasons(profits_by_season: dict[str, float]) -> list[str]:
    profits = list(profits_by_season.values())
    median_profit = statistics.median(profits)
    mad = statistics.median(abs(p - median_profit) for p in profits)
    if mad == 0:
        return []
    return [
        season
        for season, profit in profits_by_season.items()
        if (median_profit - profit) / mad > OUTLIER_MAD_MULTIPLIER
    ]


def test_marginal_eighty_is_chronically_unprofitable(generated):
    _, ground_truth = generated
    marginal_id = ground_truth["marginal_field_id"]
    seasons = ground_truth["profitability"][marginal_id]
    loss_rate = sum(1 for v in seasons.values() if v["profit_per_acre"] < 0) / len(seasons)
    assert loss_rate >= LOSS_RATE_BAD_FIELD_THRESHOLD, (
        "Marginal Eighty must classify as bad_field (chronic), not bad_year (one-off), "
        "under farm_core's own loss-rate rule"
    )


def test_east_80_keeps_exactly_one_outlier_season(generated):
    _, ground_truth = generated
    cat = ground_truth["catastrophic_year"]
    field_id, season = cat["field_id"], cat["season"]
    seasons = ground_truth["profitability"][field_id]

    loss_rate = sum(1 for v in seasons.values() if v["profit_per_acre"] < 0) / len(seasons)
    assert loss_rate < LOSS_RATE_BAD_FIELD_THRESHOLD, (
        "East 80 must not tip into bad_field -- the story is a single bad year, not a "
        "chronic loser"
    )

    profits_by_season = {s: v["profit_per_acre"] for s, v in seasons.items()}
    outliers = _outlier_seasons(profits_by_season)
    assert outliers == [str(season)], (
        f"expected exactly one outlier season ({season}), got {outliers} -- the hail year "
        "must be an unambiguous, singular outlier under the MAD rule"
    )


def test_def_aliastie_still_fires(generated):
    _, ground_truth = generated
    ids = [d["defect_id"] for d in ground_truth["defects"]]
    assert any(i.startswith("DEF-ALIASTIE-") for i in ids)


def test_def_injection_still_fires(generated):
    _, ground_truth = generated
    ids = [d["defect_id"] for d in ground_truth["defects"]]
    assert any(i.startswith("DEF-INJECTION-") for i in ids)


def test_coverage_gap_still_exists(generated):
    _, ground_truth = generated
    types = {d["type"] for d in ground_truth["defects"]}
    assert "missing_swath" in types


def test_weathershortfall_and_mgmtshortfall_fire_on_distinct_field_seasons(generated):
    _, ground_truth = generated
    ws = ground_truth["weathershortfall"]
    ms = ground_truth["mgmtshortfall"]
    assert (ws["field_id"], ws["season"]) != (ms["field_id"], ms["season"])

    ids = [d["defect_id"] for d in ground_truth["defects"]]
    assert any(i.startswith("DEF-WEATHERSHORTFALL-") for i in ids)
    assert any(i.startswith("DEF-MGMTSHORTFALL-") for i in ids)
