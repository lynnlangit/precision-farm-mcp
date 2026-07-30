"""The host's MCP client and tool router: launches the five Precision Farm
MCP servers as stdio child processes (never HTTP, never a network call --
this is what "local-first, no network access" actually looks like at the
transport level) and routes tool calls to them. The host application (query
planner, reconciliation, audit) is the only thing that talks to this; no
other layer reaches an MCP server directly.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[3]

# The one field name, across every tool response in this system, that carries
# raw farmer-authored free text (the cost ledger's Notes column) rather than
# a value the host or a test relies on for an exact match. See
# host/tests/test_untrusted_completeness.py: every string field on every
# server's response models must be classified into exactly this set or
# DETERMINISTIC_STRING_FIELDS below -- an unclassified new free-text field
# fails that test rather than silently reaching the model unwrapped.
UNTRUSTED_FREE_TEXT_FIELDS = frozenset({"notes"})

DETERMINISTIC_STRING_FIELDS = frozenset(
    {
        "canonical_id",
        "canonical_boundary_name",
        "verdict",
        "code",
        "display_name",
        "method",
        "crop",
        "cost_basis",
        "field_name",
        "line_item",
        "note",
        "data_dir",
        "built_at",
        "mapping_version",
        "product",
        "rate_unit",
        "timestamp",
        "error",
        "run",
        "pending_key",
        "exported_to",
    }
)


def _untrusted_paths(data: object, prefix: str = "") -> frozenset[str]:
    """Recursively finds every UNTRUSTED_FREE_TEXT_FIELDS key in a tool
    response, returning dotted/indexed paths into it (e.g. "notes",
    "results[2].notes"). Used to tell narrate_verified's prompt builder which
    strings to delimit as untrusted -- the response dict itself is never
    mutated, so exports and every other consumer see the farmer's own text
    unmodified.
    """
    paths: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in UNTRUSTED_FREE_TEXT_FIELDS and isinstance(value, str):
                paths.add(path)
            else:
                paths |= _untrusted_paths(value, path)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            paths |= _untrusted_paths(item, f"{prefix}[{i}]")
    return frozenset(paths)


@dataclasses.dataclass(frozen=True)
class ToolResult:
    data: dict
    untrusted_paths: frozenset[str]

# server logical name -> (directory under servers/, importable module name)
SERVERS: dict[str, tuple[str, str]] = {
    "field-registry": ("mcp-field-registry", "mcp_field_registry"),
    "yield-history": ("mcp-yield-history", "mcp_yield_history"),
    "as-applied": ("mcp-as-applied", "mcp_as_applied"),
    "cost-ledger": ("mcp-cost-ledger", "mcp_cost_ledger"),
    "report-export": ("mcp-report-export", "mcp_report_export"),
}


def _params_for(name: str, env: dict[str, str] | None = None) -> StdioServerParameters:
    dir_name, module_name = SERVERS[name]
    server_path = REPO_ROOT / "servers" / dir_name
    return StdioServerParameters(
        command="uv",
        args=["run", "--project", str(server_path), "python", "-m", module_name],
        env=env,
    )


class ToolCallFailed(Exception):
    """Raised when a tool call comes back as an MCP-protocol-level error
    (isError=True) -- distinct from a structured refusal, which is a normal,
    successfully-returned {"error": ..., "code": ...} payload.
    """


class MCPFleet:
    """Async context manager: launches the requested servers, holds one
    ClientSession per server, and exposes call() as the single choke point
    for every tool invocation the host makes.
    """

    def __init__(
        self,
        server_names: list[str] | None = None,
        env_overrides: dict[str, str] | None = None,
    ):
        self.server_names = server_names or list(SERVERS)
        # Passed straight to each spawned server's StdioServerParameters.env --
        # stdio_client merges this on top of a curated safe subset of the
        # parent's own environment (PATH, HOME, ...), it doesn't replace it.
        # Tests use this to point every server's FARM_DATA_DIR/FARM_AUDIT_LOG/
        # FARM_CONFIRM_STORE at isolated tmp paths instead of the real data/.
        self.env_overrides = env_overrides
        self._stack = contextlib.AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}

    async def __aenter__(self) -> MCPFleet:
        for name in self.server_names:
            params = _params_for(name, env=self.env_overrides)
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[name] = session
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    async def call(self, server: str, tool: str, **kwargs) -> ToolResult:
        session = self.sessions[server]
        result = await session.call_tool(tool, kwargs)
        if result.is_error:
            text = result.content[0].text if result.content else "unknown error"
            raise ToolCallFailed(f"{server}.{tool}: {text}")
        if result.structured_content is not None:
            data = result.structured_content
        elif result.content and hasattr(result.content[0], "text"):
            try:
                data = json.loads(result.content[0].text)
            except json.JSONDecodeError:
                data = {"raw": result.content[0].text}
        else:
            data = {}
        return ToolResult(data=data, untrusted_paths=_untrusted_paths(data))
