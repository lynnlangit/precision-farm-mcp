"""farm_core.records_behind: the raw records listed under "Show the records".
Checked against the raw files on disk, not against the module's own queries.
"""

import csv
from pathlib import Path

import openpyxl
import pytest

from farm_core.records_behind import KINDS, UnknownField, records_behind

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def _ticket_numbers(season: int, field_names: set[str]) -> list[int]:
    with (DATA_DIR / "scale_tickets" / f"scale_tickets_{season}.csv").open(newline="") as f:
        return sorted(
            {int(r["ticket_number"]) for r in csv.DictReader(f) if r["field_name"] in field_names}
        )


def test_every_listed_file_exists_in_the_farm_folder(farm_snapshot):
    for rec in records_behind(farm_snapshot, list(KINDS)):
        assert (DATA_DIR / rec["path"]).is_file(), rec["path"]


def test_cost_ledger_rows_are_the_rows_excel_shows(farm_snapshot):
    workbook = openpyxl.load_workbook(DATA_DIR / "cost_ledger.xlsx", read_only=True)
    records = records_behind(farm_snapshot, ["cost_ledger"], field_name="Marginal Eighty")
    assert [r["tab"] for r in records] == [str(s) for s in range(2016, 2026)]
    for rec in records:
        assert rec["rows"] == 1
        row = int(rec["which"].removeprefix("row "))
        assert workbook[rec["tab"]].cell(row=row, column=1).value.strip() == "Marginal Eighty"


def test_scale_tickets_match_the_raw_csv(farm_snapshot):
    (rec,) = records_behind(farm_snapshot, ["scale_tickets"], field_name="East 80", seasons=[2020])
    assert rec["path"] == "scale_tickets/scale_tickets_2020.csv"
    tickets = _ticket_numbers(2020, {"East 80"})
    assert rec["rows"] == len(tickets)
    assert str(tickets[0]) in rec["which"] and str(tickets[-1]) in rec["which"]


def test_misspelled_ledger_rows_are_included_under_the_field(farm_snapshot):
    # The messy farm's ledger spells N 80 "north eighty" some seasons; those
    # rows are this field's records and must be listed.
    seasons_spelled_raw = sorted(
        season for (season, raw), name in farm_snapshot.alias_map.items()
        if name == "N 80" and raw != "N 80"
    )
    assert seasons_spelled_raw, "fixture data should have naming drift on N 80"
    records = records_behind(farm_snapshot, ["cost_ledger"], field_name="north eighty")
    assert {int(r["tab"]) for r in records} >= set(seasons_spelled_raw)


def test_season_and_field_filters(farm_snapshot):
    weather = records_behind(farm_snapshot, ["weather"], seasons=[2021])
    assert [r["path"] for r in weather] == ["weather/weather_2021.csv"]
    soil = records_behind(farm_snapshot, ["soil"], field_name="Coulee Field")
    assert soil[0]["rows"] == 1 and "Coulee Field" in soil[0]["which"]


def test_unknown_field_and_kind_are_refused(farm_snapshot):
    with pytest.raises(UnknownField):
        records_behind(farm_snapshot, ["cost_ledger"], field_name="Back Forty")
    with pytest.raises(ValueError):
        records_behind(farm_snapshot, ["receipts"])


# docs/YOUR_RECORDS.md tells growers which column headings their own files
# need; they must be the headings the example files really have.
_DOC = Path(__file__).resolve().parents[2] / "docs" / "YOUR_RECORDS.md"


def _documented_columns(file_cell_prefix: str) -> list[str]:
    import re

    section = _DOC.read_text(encoding="utf-8").split("## The files you need for your own farm")[1]
    for line in section.splitlines():
        if line.startswith(f"| `{file_cell_prefix}"):
            # The headings are the code spans after the cell's last colon.
            contents = line.split("|")[3]
            return re.findall(r"`([^`]+)`", contents.rsplit(": ", 1)[1])
    raise AssertionError(f"no row for {file_cell_prefix} in {_DOC.name}")


@pytest.mark.parametrize(
    "doc_prefix, example",
    [
        ("scale_tickets/", "scale_tickets/scale_tickets_2020.csv"),
        ("yield_monitor/", "yield_monitor/yield_monitor_east_80_2020.csv"),
        ("as_applied/", "as_applied/as_applied_2024.csv"),
        ("weather/weather_", "weather/weather_2020.csv"),
        ("weather/soil_awc", "weather/soil_awc.csv"),
    ],
)
def test_your_records_doc_lists_the_real_csv_headings(doc_prefix, example):
    with (DATA_DIR / example).open(newline="") as f:
        header = next(csv.reader(f))
    assert _documented_columns(doc_prefix) == header


def test_your_records_doc_lists_the_real_unit_prices_heading():
    workbook = openpyxl.load_workbook(DATA_DIR / "cost_ledger.xlsx", read_only=True)
    header = [c for c in next(workbook["Unit Prices"].iter_rows(values_only=True)) if c]
    assert _documented_columns("cost_ledger.xlsx`, tab `Unit Prices") == header
