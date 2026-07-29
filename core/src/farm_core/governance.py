"""Read-only-by-default enforcement and export redaction.

Reading and analyzing data never requires opt-in. Anything that writes state
-- persisting a confirmed mapping, writing an export file -- goes through
require_write() first, which is the single choke point a caller can't route
around. Exports are redacted by default; identifying fields only survive an
explicit override, never a default.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

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
