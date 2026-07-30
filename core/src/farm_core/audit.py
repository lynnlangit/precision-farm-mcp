"""Append-only, hash-chained audit log. Every query, tool call, mapping
confirmation, and export gets one entry. Each entry's hash covers its own
content plus the previous entry's hash, so verify() can prove after the fact
that nothing in the log was edited, reordered, or deleted -- not just that
entries exist.

log() re-reads the true last entry from disk under an exclusive lock on
every call, rather than trusting an in-memory prev_hash: the host process and
a spawned MCP server subprocess both hold long-lived AuditLog instances
pointed at the same file, and a cached prev_hash goes stale the moment the
other process appends -- that's what forks the chain. The read is a
backward seek, not a full rescan: on a log meant to run for ten seasons, an
O(n) read on every append would make the log's lifetime cost O(n^2).
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import platform
from pathlib import Path
from typing import Any, BinaryIO

GENESIS_HASH = "0" * 64
_TAIL_CHUNK_SIZE = 4096


def _canonical_json(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


if platform.system() == "Windows":
    import msvcrt

    @contextlib.contextmanager
    def _locked(f: BinaryIO):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    @contextlib.contextmanager
    def _locked(f: BinaryIO):
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read_last_hash(f: BinaryIO) -> str:
    """Seeks from the end and reads backward in growing chunks to isolate
    the last non-empty line. Every line in this file is a single json.dumps()
    call plus one trailing "\\n" -- json.dumps escapes newlines inside string
    values, so a literal "\\n" byte only ever appears as a line separator,
    never inside a line's own content.
    """
    f.seek(0, 2)
    size = f.tell()
    if size == 0:
        return GENESIS_HASH

    chunk = _TAIL_CHUNK_SIZE
    data = b""
    pos = size
    while True:
        read_size = min(chunk, pos)
        pos -= read_size
        f.seek(pos)
        data = f.read(read_size) + data
        if pos == 0 or b"\n" in data.rstrip(b"\n"):
            break
        chunk *= 2

    for line in reversed(data.splitlines()):
        if line.strip():
            return json.loads(line)["hash"]
    return GENESIS_HASH


class AuditLog:
    def __init__(self, path: Path):
        self.path = path

    def log(self, event: str, **data: Any) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        with self.path.open("r+b") as f, _locked(f):
            prev_hash = _read_last_hash(f)
            entry = {
                "event": event,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "prev_hash": prev_hash,
                **data,
            }
            entry_hash = hashlib.sha256(_canonical_json(entry).encode("utf-8")).hexdigest()
            full_entry = {**entry, "hash": entry_hash}

            f.seek(0, 2)  # end -- another writer may have appended since we opened
            f.write((json.dumps(full_entry, sort_keys=True) + "\n").encode("utf-8"))
            f.flush()

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
