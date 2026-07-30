"""Phase B / B1 verification: farm-metrics end to end against a real
question answered through the real CLI path (not a synthetic fixture) --
proves the narration audit event actually carries the new fields in
practice, and that the CLI wrapper (JSON to stdout, optional --out file)
works. Live Ollama, matching how this project always tests the CLI layer
for real; isolated to a tmp audit log via the same env_overrides pattern
as test_audit_multiprocess.py, so it doesn't touch the real data/audit.jsonl.
"""

import json
from pathlib import Path

from farm_core.audit import AuditLog
from farm_core.metrics import build_report
from farm_host.cli import answer_question
from farm_host.metrics_cli import main as metrics_main

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
CONFIRM_STORE = Path(__file__).resolve().parents[2] / "data" / "confirmed_mappings.json"


async def test_metrics_report_reflects_a_real_answered_question(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    env = {
        "FARM_DATA_DIR": str(DATA_DIR),
        "FARM_AUDIT_LOG": str(audit_path),
        "FARM_CONFIRM_STORE": str(CONFIRM_STORE),
    }
    audit_log = AuditLog(audit_path)

    # Marginal Eighty is a chronic bad_field -- report-export never attaches
    # modeled.attribution to a bad_field verdict (see mcp-report-export's
    # server.py), so this exercises the "no modeled data yet" path even
    # though Phase C is live; the modeled-data path is covered separately
    # below.
    await answer_question(
        "was the marginal eighty a bad field or a bad year", audit_log, env_overrides=env
    )

    report = build_report(AuditLog(audit_path).entries())

    assert report["tool_grounding"]["narrations_analyzed"] == 1
    assert report["narration_faithfulness"]["narrations_analyzed"] == 1
    # No modeled data for a bad_field verdict -- must be null, not 0/0.
    assert report["tool_grounding"]["modeled_rate"] is None
    assert report["tool_grounding"]["narrations_with_modeled_data"] == 0
    # No confirmation prompts and no exports happened on this path.
    assert report["hitl_catch_rate"]["rate"] is None
    assert report["sovereignty_integrity"]["exports_performed"] == 0
    assert report["sovereignty_integrity"]["network_calls_attempted"] == 0


async def test_metrics_report_reflects_modeled_attribution_for_a_bad_year(tmp_path):
    """Phase C: a bad_year verdict carries modeled.attribution, and a
    faithful narration citing both the evidence figure and the modeled
    figure must be counted as grounded in both channels (see verification.
    check_narration_grounded_by_provenance).
    """
    audit_path = tmp_path / "audit.jsonl"
    env = {
        "FARM_DATA_DIR": str(DATA_DIR),
        "FARM_AUDIT_LOG": str(audit_path),
        "FARM_CONFIRM_STORE": str(CONFIRM_STORE),
    }
    audit_log = AuditLog(audit_path)

    await answer_question(
        "was the north eighty a bad field or a bad year", audit_log, env_overrides=env
    )

    report = build_report(AuditLog(audit_path).entries())

    assert report["tool_grounding"]["narrations_with_modeled_data"] == 1
    assert report["tool_grounding"]["modeled_rate"] == 1.0


def test_metrics_cli_prints_json_and_writes_out_file(tmp_path, capsys):
    audit_path = tmp_path / "audit.jsonl"
    AuditLog(audit_path).log("confirmation_accepted")
    AuditLog(audit_path).log("confirmation_refused")
    out_path = tmp_path / "report.json"

    exit_code = metrics_main(["--audit-log", str(audit_path), "--out", str(out_path)])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["hitl_catch_rate"]["rate"] == 0.5
    assert out_path.exists()
    assert json.loads(out_path.read_text()) == printed
