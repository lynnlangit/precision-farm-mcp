"""ServerPool keeps the MCP servers running between questions (web app).
Real servers, no Ollama: warm-up must not touch the audit log, warm calls
must return the same data as a one-off server, and a killed server must be
restarted on the next call."""

from __future__ import annotations

import os
import signal
import subprocess
import time

from farm_core.audit import AuditLog
from farm_host.mcp_client import MCPFleet
from farm_host.server_pool import POOL_SERVERS, ServerPool


def test_pool_covers_every_question_route():
    assert set(POOL_SERVERS) == {"report-export", "field-registry", "yield-history", "cost-ledger"}


async def _one_off():
    async with MCPFleet(["report-export"]) as fleet:
        result = await fleet.call("report-export", "bad_field_or_bad_year", field_name="East 80")
    return result.data


def _our_report_export_pids() -> list[int]:
    """report-export processes started by this test only -- never another
    running copy of the web app's servers."""
    rows = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True
    ).stdout.splitlines()
    procs = [(int(r.split(None, 2)[0]), int(r.split(None, 2)[1]), r.split(None, 2)[2])
             for r in rows if len(r.split(None, 2)) == 3]
    ours = {os.getpid()}
    changed = True
    while changed:
        changed = False
        for pid, ppid, _ in procs:
            if ppid in ours and pid not in ours:
                ours.add(pid)
                changed = True
    return [pid for pid, _, cmd in procs if pid in ours and "mcp_report_export" in cmd]


def test_warm_pool_matches_one_off_and_survives_a_dead_server(tmp_path):
    import asyncio

    audit = tmp_path / "audit.jsonl"
    pool = ServerPool(env_overrides={"FARM_AUDIT_LOG": str(audit)})
    try:
        pool.start()
        assert not audit.exists() or AuditLog(audit).entries() == []  # warm-up logs nothing

        def ask(fleet):
            return fleet.call("report-export", "bad_field_or_bad_year", field_name="East 80")

        started = time.monotonic()
        warm = pool.run(ask).data
        assert time.monotonic() - started < 2.0  # no server start, no snapshot build
        expected = asyncio.run(_one_off())
        for key in ("verdict", "evidence", "field_name", "modeled"):
            assert warm[key] == expected[key]

        pids = _our_report_export_pids()
        assert pids
        for pid in pids:
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        assert pool.run(ask).data["verdict"] == "bad_year"  # restarted, retried once
    finally:
        pool.close()
