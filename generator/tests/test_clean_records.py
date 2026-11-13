"""--clean (Farm 1 in the web app): the same farm, without the record-keeping
defects. Its answer key must match the default (messy) farm exactly -- the
two farms differ only in what the records say, never in what happened."""

import json

import pytest

from farm_data_gen.cli import generate
from farm_data_gen.config import SimConfig

from test_smoke import REQUIRED_DEFECT_TYPES

FARM_HISTORY_TYPES = {"split", "merge", "rename", "rental_lost", "spreadsheet_notes_column",
                      "weather_shortfall", "management_shortfall", "bad_zone"}


@pytest.fixture(scope="module")
def farms(tmp_path_factory):
    out = {}
    for clean in (False, True):
        out_dir = tmp_path_factory.mktemp("clean" if clean else "messy")
        config = SimConfig(random_seed=42, num_fields=12, num_seasons=10, clean_records=clean)
        out[clean] = (out_dir, generate(config, out_dir))
    return out


def test_clean_farm_has_the_same_answer_key(farms):
    (_, messy), (_, clean) = farms[False], farms[True]
    assert clean["profitability"] == messy["profitability"]
    assert clean["canonical_fields"] == messy["canonical_fields"]
    assert clean["identity_events"] == messy["identity_events"]


def test_clean_farm_keeps_farm_history_and_drops_record_defects(farms):
    types = {d["type"] for d in farms[True][1]["defects"]}
    assert types == FARM_HISTORY_TYPES
    assert not (REQUIRED_DEFECT_TYPES - FARM_HISTORY_TYPES) & types


def test_clean_farm_has_a_yield_monitor_every_season(farms):
    out_dir, gt = farms[True]
    for season in gt["generator"]["seasons"]:
        assert list((out_dir / "yield_monitor").glob(f"*_{season}.csv")), season
