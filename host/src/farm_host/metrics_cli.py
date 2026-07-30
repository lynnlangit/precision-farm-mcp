"""Phase B governance metrics: HITL catch rate, tool grounding, narration
faithfulness, and sovereignty integrity, computed from the audit log --
see farm_core.metrics for the definitions.

    uv run --project host farm-metrics
    uv run --project host farm-metrics --out report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from farm_core import pipeline
from farm_core.audit import AuditLog
from farm_core.metrics import build_report

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_LOG = REPO_ROOT / "data" / "audit.jsonl"
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "synthetic"
DEFAULT_CONFIRM_STORE = REPO_ROOT / "data" / "confirmed_mappings.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="farm-metrics",
        description="Report governance metrics (HITL catch rate, tool grounding, "
        "narration faithfulness, sovereignty integrity, attribution backtest) "
        "derived from the audit log and the current farm snapshot.",
    )
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_LOG)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--confirm-store", type=Path, default=DEFAULT_CONFIRM_STORE)
    parser.add_argument("--out", type=Path, default=None, help="Also write the report here.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entries = AuditLog(args.audit_log).entries()

    # attribution_backtest needs a live snapshot, not just the audit log --
    # built the same way every MCP server builds one, using whatever
    # farm-ingest already confirmed. If nothing's been confirmed yet, the
    # report simply omits that section rather than failing the whole
    # command: every other metric here still only needs the audit log.
    try:
        snapshot = pipeline.load_query_time_snapshot(
            args.data_dir, args.confirm_store, AuditLog(args.audit_log)
        )
    except pipeline.SnapshotUnconfirmed:
        snapshot = None

    report = build_report(entries, snapshot=snapshot)
    report_json = json.dumps(report, indent=2, sort_keys=True)

    print(report_json)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report_json + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
