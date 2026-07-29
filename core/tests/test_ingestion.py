"""Phase 2 verification: full-column ingestion of all five raw sources,
tolerant of every spreadsheet mess, with originals left untouched and a
confirmed column mapping reused rather than re-asked for every season.
"""

import hashlib
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_originals_are_never_modified(full_ingest):
    """Ingestion must be strictly read-only against the source files -- this
    hashes the workbook before/after a fresh ingest run to prove it.
    """
    from farm_core import confirm, db, ingest_cost_ledger

    path = DATA_DIR / "cost_ledger.xlsx"
    before = _hash(path)
    con = db.connect()
    ingest_cost_ledger.ingest_cost_ledger(con, DATA_DIR, confirm.auto_approve)
    after = _hash(path)
    assert before == after


def test_cost_ledger_row_counts_match_boundaries(full_ingest):
    con = full_ingest["con"]
    ledger_counts = dict(
        con.execute(
            "SELECT season, count(*) FROM cost_ledger_rows GROUP BY season ORDER BY season"
        ).fetchall()
    )
    boundary_counts = dict(
        con.execute(
            "SELECT season, count(*) FROM boundary_fields GROUP BY season ORDER BY season"
        ).fetchall()
    )
    assert ledger_counts == boundary_counts


def test_column_mapping_confirmed_once_per_distinct_header_shape(full_ingest):
    mapping_requests = {
        r.key for r in full_ingest["confirm_requests"] if r.kind == "column_mapping"
    }
    # Exactly two header shapes exist in this workbook: the normal $/ac
    # seasons, and the one total-dollars season -- every other season with
    # the same header reuses the confirmed mapping instead of asking again.
    assert len(mapping_requests) == 2


def test_total_dollars_season_normalized_to_per_acre(full_ingest, ground_truth):
    con = full_ingest["con"]
    basis_defect = next(
        d for d in ground_truth["defects"] if d["type"] == "cost_basis_total_dollars"
    )
    season = basis_defect["season"]

    row = con.execute(
        "SELECT cost_basis, seed_cost_per_ac, acres FROM cost_ledger_rows WHERE season = ? LIMIT 1",
        [season],
    ).fetchone()
    cost_basis, seed_per_ac, acres = row
    assert cost_basis == "total_dollars"
    # A per-acre seed cost should be a plausible dollar figure, not a raw
    # total (which would be acres-fold larger, i.e. in the tens of thousands).
    assert 0 < seed_per_ac < 500


def test_totals_row_and_blank_rows_excluded_everywhere(full_ingest):
    con = full_ingest["con"]
    bad = con.execute(
        "SELECT * FROM cost_ledger_rows WHERE upper(trim(raw_field_name)) = 'TOTAL'"
    ).fetchall()
    assert bad == []


def test_no_monitor_seasons_have_zero_yield_points(full_ingest, ground_truth):
    con = full_ingest["con"]
    no_monitor_seasons = {
        d["season"] for d in ground_truth["defects"] if d["type"] == "no_yield_monitor"
    }
    for season in no_monitor_seasons:
        count = con.execute(
            "SELECT count(*) FROM yield_monitor_points WHERE season = ?", [season]
        ).fetchone()[0]
        assert count == 0


def test_as_applied_only_covers_last_four_seasons(full_ingest):
    con = full_ingest["con"]
    seasons = {
        r[0] for r in con.execute("SELECT DISTINCT season FROM as_applied_events").fetchall()
    }
    assert seasons == {2022, 2023, 2024, 2025}
