"""Phase 1 verification: the confirmation gate isn't decorative. Proves that
auto-approving an ambiguous naming-drift alias produces a confidently silent
error (a dropped profit record, not just a wrong number), that supplying the
correct confirmed answer fixes it, and that both outcomes are visible in the
governance audit log -- not just in the final figures.
"""

from __future__ import annotations

import re
from pathlib import Path

from farm_core import confirm, governance
from farm_core.audit import AuditLog
from farm_core.pipeline import SEASONS, build_farm_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "synthetic"


def _alias_tie_defect(ground_truth):
    return next(d for d in ground_truth["defects"] if d["type"] == "ambiguous_alias_tie")


def _correct_answer_confirm(tie_key: str, correct_name: str) -> confirm.ConfirmFn:
    """auto_approve for everything except the one deliberately-ambiguous key,
    where it supplies the ground-truth-correct answer instead of the naive
    (wrong) proposal -- standing in for a human who looked at the acreage tie
    and picked correctly, the way farm-ingest's interactive_confirm would.
    """

    def _confirm(request: confirm.ConfirmationRequest) -> confirm.ConfirmationResponse:
        if request.key == tie_key:
            return confirm.ConfirmationResponse(
                approved=True, answer={"canonical_boundary_name": correct_name}
            )
        return confirm.auto_approve(request)

    return _confirm


def test_auto_approve_silently_drops_the_ambiguous_fields_profit_record(ground_truth):
    """Under auto_approve, the ambiguous alias resolves to the wrong field
    (verified directly in alias_resolution's own tests); here the consequence
    for profitability is that the correct field's profit record for that
    season doesn't exist at all -- confidently wrong, not just imprecise.
    """
    defect = _alias_tie_defect(ground_truth)
    gt_fields = ground_truth["canonical_fields"]
    season = defect["season"]
    correct_name = gt_fields[defect["field_id"]]["display_name_by_season"][str(season)]

    snapshot = build_farm_snapshot(DATA_DIR, confirm_fn=confirm.auto_approve)
    canonical_id = snapshot.canonical_id_for_name(correct_name)
    assert canonical_id is not None

    assert (canonical_id, season) not in snapshot.profit_records


def test_confirming_the_correct_answer_recovers_the_profit_record(ground_truth):
    defect = _alias_tie_defect(ground_truth)
    gt_fields = ground_truth["canonical_fields"]
    season = defect["season"]
    correct_name = gt_fields[defect["field_id"]]["display_name_by_season"][str(season)]
    tie_key = f"alias:{season}:{defect['raw_name']}"

    confirm_fn = _correct_answer_confirm(tie_key, correct_name)
    snapshot = build_farm_snapshot(DATA_DIR, confirm_fn=confirm_fn)
    canonical_id = snapshot.canonical_id_for_name(correct_name)
    assert canonical_id is not None

    record = snapshot.profit_records[(canonical_id, season)]
    gt_rec = ground_truth["profitability"][defect["field_id"]][str(season)]
    tolerance = max(50.0, abs(gt_rec["revenue"]) * 0.005)
    assert abs(record.profit - gt_rec["profit"]) < tolerance


def test_the_two_outcomes_are_both_visible_in_the_audit_log(tmp_path, ground_truth):
    """The discrepancy between "auto-approved a wrong guess" and "a human
    confirmed the right answer" must show up in the audit trail itself, not
    just be inferable from the final numbers -- that's the actual governance
    claim ConfirmationGate exists to back up.
    """
    defect = _alias_tie_defect(ground_truth)
    gt_fields = ground_truth["canonical_fields"]
    season = defect["season"]
    correct_name = gt_fields[defect["field_id"]]["display_name_by_season"][str(season)]
    tie_key = f"alias:{season}:{defect['raw_name']}"

    wrong_audit = AuditLog(tmp_path / "wrong_audit.jsonl")
    wrong_gate = governance.ConfirmationGate(
        tmp_path / "wrong_store.json", confirm.auto_approve, wrong_audit
    )
    build_farm_snapshot(DATA_DIR, confirm_fn=wrong_gate)

    right_audit = AuditLog(tmp_path / "right_audit.jsonl")
    right_gate = governance.ConfirmationGate(
        tmp_path / "right_store.json",
        _correct_answer_confirm(tie_key, correct_name),
        right_audit,
    )
    build_farm_snapshot(DATA_DIR, confirm_fn=right_gate)

    wrong_name = gt_fields[defect["naive_wrong_field_id"]]["display_name_by_season"][str(season)]
    wrong_entry = next(e for e in wrong_audit.entries() if e.get("proposal_id") == tie_key)
    right_entry = next(e for e in right_audit.entries() if e.get("proposal_id") == tie_key)

    assert wrong_entry["decision"] == {"canonical_boundary_name": wrong_name}
    assert right_entry["decision"] == {"canonical_boundary_name": correct_name}
    assert wrong_entry["decision"] != right_entry["decision"]
    assert wrong_audit.verify()
    assert right_audit.verify()


_AUTO_APPROVE_REF = re.compile(r"\bauto_approve\b")

# The one sanctioned non-test reference: farm-ingest's
# --auto-approve-synthetic-only flag (host/src/farm_host/ingest_cli.py),
# which is itself structurally refused (SyntheticDataRequired) outside
# data/synthetic/ -- see host/tests/test_ingest_cli.py. Everything else,
# especially any MCP server (which must stay non-interactive and fail
# closed with no exceptions), must never reference it.
_ALLOWED_AUTO_APPROVE_REFERENCES = {"host/src/farm_host/ingest_cli.py"}


def test_no_server_or_host_code_path_uses_auto_approve():
    """auto_approve is a test-only shortcut (see confirm.py's docstring),
    with exactly one sanctioned exception (see
    _ALLOWED_AUTO_APPROVE_REFERENCES above); any other server or host code
    path reaching production data through it would mean the fail-closed
    default silently isn't fail-closed at all.
    """
    violations = []
    for base in (REPO_ROOT / "servers", REPO_ROOT / "host"):
        for path in base.rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            relative = str(path.relative_to(REPO_ROOT))
            if relative in _ALLOWED_AUTO_APPROVE_REFERENCES:
                continue
            if _AUTO_APPROVE_REF.search(path.read_text(encoding="utf-8")):
                violations.append(relative)
    assert not violations, f"auto_approve referenced outside tests: {violations}"
