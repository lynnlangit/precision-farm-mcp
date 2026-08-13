"""farm-ingest's --auto-approve-synthetic-only flag: reuses the existing
confirm.auto_approve (no new confirm function) but is structurally refused
outside data/synthetic/, since DEF-ALIASTIE exists specifically to prove
auto-approval gives a confidently wrong answer on real data.
"""

from pathlib import Path

import pytest

from farm_core import confirm
from farm_core.audit import AuditLog
from farm_host import ingest_cli
from farm_host.ingest_cli import DEFAULT_DATA_DIR, SyntheticDataRequired, main, run_ingest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_auto_approve_synthetic_only_succeeds_against_real_synthetic_data(tmp_path):
    confirm_store = tmp_path / "confirmed_mappings.json"
    audit_log = AuditLog(tmp_path / "audit.jsonl")

    counts = run_ingest(
        DEFAULT_DATA_DIR,
        confirm_store,
        audit_log,
        auto_approve_synthetic_only=True,
    )

    assert counts["total"] > 0
    assert counts["refused"] == 0  # auto_approve never refuses
    assert confirm_store.is_file()


def test_auto_approve_synthetic_only_refuses_outside_synthetic_dir(tmp_path):
    fake_real_data_dir = tmp_path / "my_real_farm_data"
    fake_real_data_dir.mkdir()
    confirm_store = tmp_path / "confirmed_mappings.json"
    audit_log = AuditLog(tmp_path / "audit.jsonl")

    with pytest.raises(SyntheticDataRequired):
        run_ingest(
            fake_real_data_dir,
            confirm_store,
            audit_log,
            auto_approve_synthetic_only=True,
        )

    assert not confirm_store.exists()


def test_auto_approve_synthetic_only_refuses_repo_root(tmp_path):
    """A directory that merely contains data/synthetic/ as a subdirectory
    (e.g. accidentally passing the repo root) must not qualify -- only
    data/synthetic/ itself or a path inside it.
    """
    confirm_store = tmp_path / "confirmed_mappings.json"
    audit_log = AuditLog(tmp_path / "audit.jsonl")

    with pytest.raises(SyntheticDataRequired):
        run_ingest(
            REPO_ROOT,
            confirm_store,
            audit_log,
            auto_approve_synthetic_only=True,
        )


def test_main_exits_nonzero_when_auto_approve_refused(tmp_path):
    fake_real_data_dir = tmp_path / "my_real_farm_data"
    fake_real_data_dir.mkdir()
    exit_code = main(
        [
            "--data-dir",
            str(fake_real_data_dir),
            "--confirm-store",
            str(tmp_path / "confirmed_mappings.json"),
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
            "--auto-approve-synthetic-only",
        ]
    )
    assert exit_code == 1


def test_run_ingest_exits_nonzero_on_confirmation_rejected(tmp_path, monkeypatch):
    """A human rejecting a proposal (ConfirmationRejected) must stop ingest
    with a non-zero exit -- an accidental `y`-mashed run shouldn't silently
    report success.
    """

    def fake_build_farm_snapshot(data_dir, confirm_fn):
        raise confirm.ConfirmationRejected("farmer rejected a proposal")

    monkeypatch.setattr(ingest_cli, "build_farm_snapshot", fake_build_farm_snapshot)

    with pytest.raises(SystemExit) as exc_info:
        run_ingest(
            DEFAULT_DATA_DIR,
            tmp_path / "confirmed_mappings.json",
            AuditLog(tmp_path / "audit.jsonl"),
        )
    assert exc_info.value.code == 1
