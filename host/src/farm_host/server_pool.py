"""Keeps the MCP servers running between questions, for the grower web app.

Without this, every question starts its server with `uv run` and the server
rebuilds the farm data snapshot on its first tool call: about 4 seconds per
question before Gemma does anything. A ServerPool starts every server the
question types route to (all six) once, warms each snapshot, and then reuses them.

The servers, their tools, the audit log and every check are unchanged; only
when the servers start differs. The CLI still starts one server per question.

Trade-off: a running server keeps the snapshot it loaded. After regenerating
data or re-running farm-ingest, restart the app (or call close()).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

import anyio
from mcp.shared.exceptions import MCPError

from farm_core.pipeline import SEASONS

from .cli import _INTENT_TO_SERVER
from .mcp_client import MCPFleet

T = TypeVar("T")

# What a dead or hung-up server looks like from the client side.
_CONNECTION_ERRORS = (
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
    ConnectionError,
    MCPError,
)

# Every server a question can route to, in a stable order.
POOL_SERVERS: tuple[str, ...] = tuple(dict.fromkeys(_INTENT_TO_SERVER.values()))

# One deliberately unanswerable call per server: it makes the server build
# its snapshot now, and comes back as a refusal before anything is written
# to the audit log (a not-found name, or season 0).
_WARMUP_CALLS: dict[str, tuple[str, dict]] = {
    "report-export": ("bad_field_or_bad_year", {"field_name": "__warmup__"}),
    "field-registry": ("resolve_field_name", {"raw_name": "__warmup__", "season": 0}),
    "yield-history": (
        "get_yield_reconciliation", {"field_name": "__warmup__", "season": SEASONS[0]}
    ),
    "cost-ledger": ("get_cost_reconciliation", {"field_name": "__warmup__", "season": 0}),
    "weather-history": ("get_season_weather", {"season": 0}),
    "as-applied": ("get_applied_inputs", {"field_name": "__warmup__", "season": 0}),
}


class ServerPool:
    """Owns one MCPFleet on a private event loop in a background thread.

    run() is called from any thread (Gradio's workers) and blocks until the
    coroutine finishes there. Questions are answered one at a time.
    """

    def __init__(self, env_overrides: dict[str, str] | None = None):
        self.env_overrides = env_overrides
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="farm-server-pool", daemon=True
        )
        self._thread.start()
        self._fleet: MCPFleet | None = None
        self._stop: asyncio.Event | None = None
        self._owner: asyncio.Task | None = None
        self._lock = asyncio.Lock()  # binds to the pool loop on first use

    # -- on the pool's loop ------------------------------------------------
    # The servers' stdio connections must be opened and closed by the same
    # task (anyio cancel scopes), so one long-lived owner task holds the
    # fleet open until told to stop; questions only call into it.
    async def _own_fleet(self, ready: asyncio.Future, stop: asyncio.Event) -> None:
        try:
            async with MCPFleet(list(POOL_SERVERS), env_overrides=self.env_overrides) as fleet:
                # Each server is its own process, so their snapshots build in parallel.
                await asyncio.gather(
                    *(
                        fleet.call(server, tool, **args)
                        for server, (tool, args) in _WARMUP_CALLS.items()
                        if server in fleet.sessions
                    )
                )
                ready.set_result(fleet)
                await stop.wait()
        except BaseException as e:  # noqa: BLE001 -- handed to whoever is waiting
            if not ready.done():
                ready.set_exception(e)
            else:
                raise

    async def _ensure_fleet(self) -> MCPFleet:
        if self._fleet is None:
            ready: asyncio.Future = self._loop.create_future()
            stop = asyncio.Event()
            owner = self._loop.create_task(self._own_fleet(ready, stop))
            fleet = await ready
            self._fleet, self._stop, self._owner = fleet, stop, owner
        return self._fleet

    async def _drop_fleet(self) -> None:
        if self._fleet is None:
            return
        self._fleet = None
        self._stop.set()
        try:
            await self._owner
        except Exception:  # noqa: BLE001 -- a dead server can't be closed cleanly
            pass

    async def _with_fleet(self, fn: Callable[[MCPFleet], Awaitable[T]]) -> T:
        async with self._lock:
            fleet = await self._ensure_fleet()
            try:
                return await fn(fleet)
            except _CONNECTION_ERRORS:
                # A server died mid-session: start fresh once and retry.
                await self._drop_fleet()
                fleet = await self._ensure_fleet()
                return await fn(fleet)

    # -- from any thread ---------------------------------------------------
    def run(self, fn: Callable[[MCPFleet], Awaitable[T]]) -> T:
        return asyncio.run_coroutine_threadsafe(self._with_fleet(fn), self._loop).result()

    def start(self) -> None:
        """Start and warm every server now (blocks until they're ready)."""

        async def _start() -> None:
            async with self._lock:
                await self._ensure_fleet()

        asyncio.run_coroutine_threadsafe(_start(), self._loop).result()

    def start_in_background(self) -> None:
        """Start warming without waiting, so the page opens right away."""
        threading.Thread(target=self._start_quietly, name="farm-pool-warmup", daemon=True).start()

    def _start_quietly(self) -> None:
        try:
            self.start()
        except Exception:  # noqa: BLE001 -- the first question retries and reports it
            pass

    def close(self) -> None:
        async def _close() -> None:
            async with self._lock:
                await self._drop_fleet()

        asyncio.run_coroutine_threadsafe(_close(), self._loop).result()
