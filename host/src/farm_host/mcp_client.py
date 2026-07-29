"""The host's MCP client and tool router: launches the five Precision Farm
MCP servers as stdio child processes (never HTTP, never a network call --
this is what "local-first, no network access" actually looks like at the
transport level) and routes tool calls to them. The host application (query
planner, reconciliation, audit) is the only thing that talks to this; no
other layer reaches an MCP server directly.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[3]

# server logical name -> (directory under servers/, importable module name)
SERVERS: dict[str, tuple[str, str]] = {
    "field-registry": ("mcp-field-registry", "mcp_field_registry"),
    "yield-history": ("mcp-yield-history", "mcp_yield_history"),
    "as-applied": ("mcp-as-applied", "mcp_as_applied"),
    "cost-ledger": ("mcp-cost-ledger", "mcp_cost_ledger"),
    "report-export": ("mcp-report-export", "mcp_report_export"),
}


def _params_for(name: str) -> StdioServerParameters:
    dir_name, module_name = SERVERS[name]
    server_path = REPO_ROOT / "servers" / dir_name
    return StdioServerParameters(
        command="uv",
        args=["run", "--project", str(server_path), "python", "-m", module_name],
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

    def __init__(self, server_names: list[str] | None = None):
        self.server_names = server_names or list(SERVERS)
        self._stack = contextlib.AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}

    async def __aenter__(self) -> MCPFleet:
        for name in self.server_names:
            params = _params_for(name)
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[name] = session
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    async def call(self, server: str, tool: str, **kwargs) -> dict:
        session = self.sessions[server]
        result = await session.call_tool(tool, kwargs)
        if result.is_error:
            text = result.content[0].text if result.content else "unknown error"
            raise ToolCallFailed(f"{server}.{tool}: {text}")
        if result.structured_content is not None:
            return result.structured_content
        if result.content and hasattr(result.content[0], "text"):
            try:
                return json.loads(result.content[0].text)
            except json.JSONDecodeError:
                return {"raw": result.content[0].text}
        return {}
