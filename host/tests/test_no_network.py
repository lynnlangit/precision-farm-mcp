"""Phase 6 verification: nothing leaves the laptop. Two complementary checks:

1. Dynamic -- every socket connection actually opened during a full
   question-answer cycle (parse -> MCP tool call -> narrate) is loopback
   only. This is the CLI process's own network behavior; Ollama itself runs
   as a separate local server, but the client library still opens a real
   socket, so this is a genuine end-to-end check, not a mock.
2. Static -- the five MCP server packages, which run as separate stdio
   subprocesses this test's socket patch can't observe directly, are scanned
   for any direct import of a networking library. They should have none:
   their only I/O is DuckDB (local file) and stdio.
"""

import ast
import socket
from pathlib import Path

import pytest

from farm_core.audit import AuditLog
from farm_host.cli import answer_question

ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}
SERVERS_DIR = Path(__file__).resolve().parents[2] / "servers"
FORBIDDEN_NETWORK_MODULES = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "urllib.request",
    "urllib3",
    "socket",
    "http.client",
}


@pytest.fixture
def track_connections(monkeypatch):
    # ollama.chat is a bound method captured on a Client() built once at
    # import time (ollama/__init__.py: "_client = Client(); chat =
    # _client.chat") -- not a lazy lookup, so it keeps reusing that same
    # client's pooled connection for the rest of the process. If an earlier
    # live-Ollama test in this run already warmed one up (order-dependent
    # -- e.g. test_injection_defect.py, if it runs first), that socket gets
    # reused here rather than reconnected, so this fixture's own sanity
    # check below would fail with no real non-loopback connection ever
    # having happened. Rebinding to a fresh Client()'s .chat makes the
    # observation window reliable regardless of run order; it doesn't
    # change what's verified.
    import ollama

    ollama.chat = ollama.Client().chat

    connections: list = []
    original_connect = socket.socket.connect

    def recording_connect(self, address):
        connections.append(address)
        return original_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", recording_connect)
    return connections


async def test_no_non_local_connections_during_full_question_cycle(track_connections, tmp_path):
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    answer = await answer_question(
        "was the marginal eighty a bad field or a bad year", audit_log
    )
    assert answer  # sanity: the call actually completed and produced something

    non_local = [
        addr
        for addr in track_connections
        if isinstance(addr, tuple) and addr and addr[0] not in ALLOWED_HOSTS
    ]
    assert not non_local, f"non-local connection(s) attempted: {non_local}"
    # Sanity: this test is only meaningful if it actually observed some
    # loopback traffic (the Ollama calls) -- an empty list could mean the
    # patch silently didn't apply, not that nothing connected.
    assert track_connections, "expected at least the Ollama loopback connections to be recorded"


def test_mcp_servers_have_no_direct_network_imports():
    """The five MCP servers' only I/O is DuckDB (local files) and stdio.
    None of their own code should import a networking library directly --
    if a future change added one, this fails loudly rather than silently.
    """
    violations = []
    for server_file in SERVERS_DIR.glob("*/src/*/server.py"):
        tree = ast.parse(server_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module} if node.module else set()
            else:
                continue
            hit = names & FORBIDDEN_NETWORK_MODULES
            if hit:
                violations.append((server_file.name, hit))

    assert not violations, f"MCP servers importing network libraries: {violations}"
