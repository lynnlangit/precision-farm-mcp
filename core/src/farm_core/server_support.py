"""What every MCP server shares: which farm's files it reads, the snapshot
and audit log it opens once per process, the `confirmation_required`
refusal, and the provenance block on every response.

The host starts each server with FARM_DATA_DIR, FARM_CONFIRM_STORE and
FARM_AUDIT_LOG set for the farm being asked about (farm_host.farms); without
them a server reads Farm 2 (data/synthetic). Each server is its own process,
so the caches below hold one farm's snapshot per server.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from . import pipeline
from .audit import AuditLog

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.getenv("FARM_DATA_DIR", str(REPO_ROOT / "data" / "synthetic")))
AUDIT_LOG_PATH = Path(os.getenv("FARM_AUDIT_LOG", str(REPO_ROOT / "data" / "audit.jsonl")))
CONFIRM_STORE_PATH = Path(
    os.getenv("FARM_CONFIRM_STORE", str(REPO_ROOT / "data" / "confirmed_mappings.json"))
)


class SnapshotProvenance(BaseModel):
    """Which snapshot an answer came from. Excluded from grounding: its
    digits (timestamps, counts) never ground a narrated number."""

    data_dir: str
    built_at: str
    source_file_count: int


@functools.lru_cache(maxsize=1)
def audit_log() -> AuditLog:
    return AuditLog(AUDIT_LOG_PATH)


@functools.lru_cache(maxsize=1)
def snapshot() -> pipeline.FarmSnapshot:
    """Built once, from what farm-ingest confirmed; raises SnapshotUnconfirmed
    rather than guessing at anything it didn't."""
    return pipeline.load_query_time_snapshot(DATA_DIR, CONFIRM_STORE_PATH, audit_log())


def confirmation_required(exc: pipeline.SnapshotUnconfirmed) -> dict[str, Any]:
    return {
        "error": str(exc),
        "code": "confirmation_required",
        "pending_key": exc.request.key,
        "run": "farm-ingest",
    }


def confirmation_guarded(fn: Callable[..., dict]) -> Callable[..., dict]:
    """Turns an unconfirmed snapshot into a structured refusal instead of a
    tool error, so the host can tell the grower to run farm-ingest."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            return fn(*args, **kwargs)
        except pipeline.SnapshotUnconfirmed as e:
            return confirmation_required(e)

    return wrapper


def provenance(mapping_version: str | None = None) -> dict[str, Any]:
    snap = snapshot()
    prov: dict[str, Any] = {
        "data_dir": str(snap.data_dir),
        "built_at": snap.built_at,
        "source_file_count": len(snap.source_files),
    }
    if mapping_version is not None:
        prov["mapping_version"] = mapping_version
    return prov
