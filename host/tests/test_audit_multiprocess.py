"""Phase A / A1 verification: the audit chain survives real multi-process
concurrent writers, not just a fresh per-test file written by one process.
The host process and each spawned MCP server subprocess hold independent
AuditLog instances pointed at the same file; before the re-read-under-lock
fix, a cached prev_hash in one process went stale the moment another
process appended, forking the chain. This test is the one that actually
exercises that path: two real server subprocesses plus the host, all
logging to one shared file within a single flow.
"""

from pathlib import Path

from farm_core.audit import AuditLog
from farm_host.mcp_client import MCPFleet


async def test_audit_chain_survives_host_plus_two_real_server_subprocesses(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    env = {
        "FARM_DATA_DIR": str(Path(__file__).resolve().parents[2] / "data" / "synthetic"),
        "FARM_AUDIT_LOG": str(audit_path),
        "FARM_CONFIRM_STORE": str(
            Path(__file__).resolve().parents[2] / "data" / "confirmed_mappings.json"
        ),
    }
    host_log = AuditLog(audit_path)

    host_log.log("query", question="was the north eighty a bad field or a bad year")
    async with MCPFleet(["report-export", "field-registry"], env_overrides=env) as fleet:
        await fleet.call("report-export", "bad_field_or_bad_year", field_name="Marginal Eighty")
        await fleet.call("field-registry", "resolve_field_name", raw_name="N 80", season=2020)
    host_log.log("narration", question="was the north eighty a bad field or a bad year")

    final = AuditLog(audit_path)
    entries = final.entries()
    events = [e["event"] for e in entries]

    assert events.count("query") == 1
    assert events.count("narration") == 1
    assert "tool_call" in events  # logged by the server subprocesses themselves
    assert len(entries) >= 4  # host's 2 + at least one tool_call per server
    assert final.verify() is True
