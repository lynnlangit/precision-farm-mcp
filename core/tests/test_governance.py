"""Phase 3 verification: the audit log is genuinely tamper-evident, writes
are blocked by default, and exports are redacted by default."""

import json

import pytest

from farm_core.audit import AuditLog
from farm_core.governance import HostConfig, WriteNotAllowed, export_json, redact


@pytest.fixture
def audit_log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def test_audit_log_verifies_clean(audit_log):
    audit_log.log("query", question="which fields made money")
    audit_log.log("tool_call", tool="field-registry.resolve")
    audit_log.log("export", path="out.json")
    assert audit_log.verify()
    assert len(audit_log.entries()) == 3


def test_audit_log_detects_tampering(audit_log):
    audit_log.log("query", question="a")
    audit_log.log("query", question="b")

    lines = audit_log.path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["question"] = "TAMPERED"
    lines[0] = json.dumps(tampered, sort_keys=True)
    audit_log.path.write_text("\n".join(lines) + "\n")

    assert not AuditLog(audit_log.path).verify()


def test_audit_log_detects_reordering(audit_log):
    audit_log.log("query", question="a")
    audit_log.log("query", question="b")
    lines = audit_log.path.read_text().splitlines()
    audit_log.path.write_text("\n".join(reversed(lines)) + "\n")
    assert not AuditLog(audit_log.path).verify()


def test_export_blocked_without_write_flag(tmp_path, audit_log):
    host = HostConfig(allow_write=False)
    with pytest.raises(WriteNotAllowed):
        export_json({"profit": 100}, tmp_path / "out.json", host, audit_log)
    assert not (tmp_path / "out.json").exists()


def test_export_succeeds_with_write_flag_and_logs(tmp_path, audit_log):
    host = HostConfig(allow_write=True)
    export_json({"profit": 100}, tmp_path / "out.json", host, audit_log)
    assert (tmp_path / "out.json").exists()
    entries = audit_log.entries()
    assert entries[-1]["event"] == "export"
    assert entries[-1]["redacted"] is True


def test_redaction_strips_coordinates_and_identity_by_default():
    payload = {
        "field_name": "N 80",
        "lat": 47.1,
        "lon": -97.5,
        "grower_name": "Jane Farmer",
        "profit": 500,
    }
    redacted = redact(payload)
    assert "lat" not in redacted and "lon" not in redacted
    assert "grower_name" not in redacted
    assert redacted["field_name"] == "N 80"
    assert redacted["profit"] == 500


def test_redaction_recurses_into_nested_structures():
    payload = {"points": [{"lat": 1.0, "lon": 2.0, "value": 5}]}
    redacted = redact(payload)
    assert redacted["points"] == [{"value": 5}]


def test_redaction_override_keeps_everything():
    payload = {"lat": 1.0, "grower_name": "Jane"}
    assert redact(payload, allow_identifying=True) == payload
