"""Read-only-by-default enforcement and export redaction.

Reading and analyzing data never requires opt-in. Anything that writes state
-- persisting a confirmed mapping, writing an export file -- goes through
require_write() first, which is the single choke point a caller can't route
around. Exports are redacted by default; identifying fields only survive an
explicit override, never a default.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from . import confirm as confirm_mod
from .audit import AuditLog

_COORDINATE_KEYS = {
    "lat",
    "lon",
    "latitude",
    "longitude",
    "min_lat",
    "max_lat",
    "min_lon",
    "max_lon",
}
_IDENTITY_KEYS = {"grower_name", "grower_id", "operation_name", "owner", "farmer_name"}


class WriteNotAllowed(Exception):
    """Raised when a write is attempted while the host is in read-only mode."""


@dataclasses.dataclass
class HostConfig:
    allow_write: bool = False

    def require_write(self, action: str) -> None:
        if not self.allow_write:
            raise WriteNotAllowed(
                f"{action!r} requires an explicit write flag; the host is read-only by default."
            )


def redact(payload: Any, allow_identifying: bool = False) -> Any:
    """Recursively strip coordinate and grower-identity fields from an export
    payload unless explicitly overridden. Never mutates the input.
    """
    if allow_identifying:
        return payload
    if isinstance(payload, dict):
        return {
            k: redact(v, allow_identifying)
            for k, v in payload.items()
            if k not in _COORDINATE_KEYS and k not in _IDENTITY_KEYS
        }
    if isinstance(payload, list):
        return [redact(v, allow_identifying) for v in payload]
    return payload


def export_json(
    payload: Any,
    path: Path,
    host: HostConfig,
    audit_log: AuditLog,
    allow_identifying: bool = False,
) -> None:
    host.require_write(f"export to {path}")
    redacted = redact(payload, allow_identifying)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_log.log(
        "export",
        path=str(path),
        redacted=not allow_identifying,
    )


def _header_shape_hash(request: confirm_mod.ConfirmationRequest) -> str | None:
    header_row = request.context.get("header_row")
    if header_row is None:
        return None
    return hashlib.sha256(json.dumps(header_row, sort_keys=True).encode()).hexdigest()[:16]


class ConfirmationGate:
    """The named, governance-owned confirmation gate: every naming-drift
    alias, identity event, and column-mapping proposal passes through here on
    its way to a confirm_fn. Wraps PersistedConfirm (the mechanism, unchanged)
    and adds one audit event per key the first time it's decided -- cache
    hits on an already-decided key aren't re-logged, so a server restart
    doesn't re-emit the same event on every boot.
    """

    def __init__(
        self,
        store_path: Path,
        terminal: confirm_mod.ConfirmFn,
        audit_log: AuditLog,
        recheck: bool = False,
    ):
        self._persisted = confirm_mod.PersistedConfirm(store_path, inner=terminal, recheck=recheck)
        self._audit_log = audit_log

    def __call__(
        self, request: confirm_mod.ConfirmationRequest
    ) -> confirm_mod.ConfirmationResponse:
        already_decided = self._persisted.has_key(request.key)
        previous_answer = self._persisted.current_answer(request.key) if already_decided else None
        response = self._persisted(request)

        if already_decided and not self._persisted.recheck:
            return response  # cache hit, no fresh decision made -- not logged

        if not response.approved:
            event = "confirmation_refused"
        elif already_decided and response.answer != previous_answer:
            event = "confirmation_corrected"
        else:
            event = "confirmation_accepted"

        self._audit_log.log(
            event,
            proposal_id=request.key,
            kind=request.kind,
            source_file=request.context.get("source_file"),
            header_shape_hash=_header_shape_hash(request),
            proposed=request.proposal,
            decision=response.answer if response.approved else None,
        )
        return response
