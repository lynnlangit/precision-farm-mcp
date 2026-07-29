"""Append-only, hash-chained audit log. Every query, tool call, mapping
confirmation, and export gets one entry. Each entry's hash covers its own
content plus the previous entry's hash, so verify() can prove after the fact
that nothing in the log was edited, reordered, or deleted -- not just that
entries exist.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64


def _canonical_json(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self._prev_hash = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS_HASH
        last_line = None
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line
        if last_line is None:
            return GENESIS_HASH
        return json.loads(last_line)["hash"]

    def log(self, event: str, **data: Any) -> dict:
        entry = {
            "event": event,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "prev_hash": self._prev_hash,
            **data,
        }
        entry_hash = hashlib.sha256(_canonical_json(entry).encode("utf-8")).hexdigest()
        full_entry = {**entry, "hash": entry_hash}

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(full_entry, sort_keys=True) + "\n")

        self._prev_hash = entry_hash
        return full_entry

    def verify(self) -> bool:
        """Recompute every entry's hash from its content and the previous
        entry's hash, and confirm it matches what was stored. Returns False
        if any entry was tampered with, reordered, or removed.
        """
        if not self.path.exists():
            return True
        prev = GENESIS_HASH
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                stored_hash = entry.pop("hash")
                if entry["prev_hash"] != prev:
                    return False
                recomputed = hashlib.sha256(_canonical_json(entry).encode("utf-8")).hexdigest()
                if recomputed != stored_hash:
                    return False
                prev = stored_hash
        return True

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
