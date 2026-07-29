"""The ingest half of the ingest/query split (see farm_core.pipeline and
farm_core.governance.ConfirmationGate): the one place a human is actually
asked to confirm a naming-drift alias, identity event, or column mapping.
Run this once after generating/receiving new data; every MCP server (and
farm-cli) then reuses whatever it persisted and refuses, rather than
guessing, at anything this command hasn't confirmed.

    uv run --project host farm-ingest
    uv run --project host farm-ingest --recheck   # re-ask already-confirmed keys
"""

from __future__ import annotations

import argparse
from pathlib import Path

from farm_core import confirm, governance
from farm_core.audit import AuditLog
from farm_core.pipeline import build_farm_snapshot

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "synthetic"
DEFAULT_CONFIRM_STORE = REPO_ROOT / "data" / "confirmed_mappings.json"
DEFAULT_AUDIT_LOG = REPO_ROOT / "data" / "audit.jsonl"


def _counting(gate: governance.ConfirmationGate) -> tuple[confirm.ConfirmFn, dict[str, int]]:
    counts = {"approved": 0, "refused": 0, "total": 0}

    def wrapped(request: confirm.ConfirmationRequest) -> confirm.ConfirmationResponse:
        response = gate(request)
        counts["total"] += 1
        counts["approved" if response.approved else "refused"] += 1
        return response

    return wrapped, counts


def run_ingest(
    data_dir: Path, confirm_store: Path, audit_log: AuditLog, recheck: bool = False
) -> dict[str, int]:
    gate = governance.ConfirmationGate(
        confirm_store, confirm.interactive_confirm, audit_log, recheck=recheck
    )
    confirm_fn, counts = _counting(gate)

    try:
        snapshot = build_farm_snapshot(data_dir, confirm_fn=confirm_fn)
    except confirm.ConfirmationRejected as e:
        print(f"\nIngest stopped: {e}")
        print(f"({counts['approved']} confirmed, {counts['refused']} refused before this)")
        raise SystemExit(1) from e

    print(
        f"\nIngested {len(snapshot.source_files)} source file(s), "
        f"{len(snapshot.profit_records)} field/season profit records."
    )
    print(f"Confirmation decisions this run: {counts['approved']} approved, {counts['refused']} refused.")
    print(f"Persisted to {confirm_store}")
    return counts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="farm-ingest",
        description="Confirm every naming-drift alias, identity event, and column "
        "mapping for a data directory, once, interactively. MCP servers and "
        "farm-cli read only what this persists -- they never prompt.",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--confirm-store", type=Path, default=DEFAULT_CONFIRM_STORE)
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_LOG)
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="Re-ask every already-confirmed key too, instead of only new ones. "
        "A correction is appended as a new version, not overwritten.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audit_log = AuditLog(args.audit_log)
    run_ingest(args.data_dir, args.confirm_store, audit_log, recheck=args.recheck)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
