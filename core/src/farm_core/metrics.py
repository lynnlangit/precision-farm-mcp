"""Governance metrics, derived from the audit log. Phase B: these were
uncomputable before Phase 1 made confirmations real and Phase A made the
audit log trustworthy under concurrency and the grounding check
provenance-aware. Every function here is a pure `list[dict] -> dict`
transform of `AuditLog.entries()`'s output -- no I/O, no side effects, so
the definitions are stable and independently testable.

A rate is reported as `None`, never a misleading `0`, when its denominator
is zero -- the same convention `verification.check_narration_grounded_by_
provenance` already uses for "no modeled data yet". Narration events logged
before this module existed lack the fields these metrics need (`grounded`,
`attempts`, ...); such entries are counted and excluded, not silently
treated as a failure.
"""

from __future__ import annotations

import datetime
from typing import Any

_CONFIRMATION_EVENTS = ("confirmation_accepted", "confirmation_corrected", "confirmation_refused")


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def hitl_catch_rate(entries: list[dict]) -> dict[str, Any]:
    """Of confirmation decisions actually made (not cache hits -- those
    never reach the audit log at all, see governance.ConfirmationGate),
    what fraction weren't a rubber stamp of the naive proposal.
    """
    counts = {event: 0 for event in _CONFIRMATION_EVENTS}
    for entry in entries:
        if entry.get("event") in counts:
            counts[entry["event"]] += 1

    accepted = counts["confirmation_accepted"]
    corrected = counts["confirmation_corrected"]
    refused = counts["confirmation_refused"]
    total = accepted + corrected + refused

    return {
        "definition": (
            "(corrected + refused) / (accepted + corrected + refused) -- "
            "confirmation decisions actually made, not reused from cache"
        ),
        "rate": _rate(corrected + refused, total),
        "accepted": accepted,
        "corrected": corrected,
        "refused": refused,
    }


def _narration_entries_with(entries: list[dict], *fields: str) -> list[dict]:
    return [
        e
        for e in entries
        if e.get("event") == "narration" and all(f in e for f in fields)
    ]


def tool_grounding(entries: list[dict]) -> dict[str, Any]:
    """Two rates, per the A3 split: whether narrated measured/derived
    numbers were grounded, and separately whether narrated modeled numbers
    were -- so a metric can never blend "the tool cited a real number" with
    "the model's own output happened to check out".
    """
    graded = _narration_entries_with(entries, "grounded")
    measured_or_derived_grounded = sum(1 for e in graded if e["grounded"])

    with_modeled = [e for e in graded if e.get("modeled_grounded") is not None]
    modeled_grounded = sum(1 for e in with_modeled if e["modeled_grounded"])

    return {
        "definition": (
            "measured_or_derived_rate = narrations grounded / narrations analyzed; "
            "modeled_rate = narrations with modeled data grounded / narrations "
            "with modeled data at all (null until Phase C populates `modeled`)"
        ),
        "measured_or_derived_rate": _rate(measured_or_derived_grounded, len(graded)),
        "modeled_rate": _rate(modeled_grounded, len(with_modeled)),
        "narrations_analyzed": len(graded),
        "narrations_with_modeled_data": len(with_modeled),
    }


def narration_faithfulness(entries: list[dict]) -> dict[str, Any]:
    """The existing per-narration verification (grounded and non-
    contradictory) expressed as rates across a run, not one pass/fail per
    question: how often the model got it right immediately, and how often
    it needed the deterministic fallback instead of an unverified answer.
    """
    graded = _narration_entries_with(entries, "attempts", "used_fallback")
    first_attempt = sum(1 for e in graded if e["attempts"] == 1)
    fallback = sum(1 for e in graded if e["used_fallback"])

    return {
        "definition": (
            "first_attempt_rate = narrations accepted without a retry / narrations "
            "analyzed; fallback_rate = narrations that hit the deterministic "
            "template / narrations analyzed"
        ),
        "first_attempt_rate": _rate(first_attempt, len(graded)),
        "fallback_rate": _rate(fallback, len(graded)),
        "narrations_analyzed": len(graded),
    }


def sovereignty_integrity(entries: list[dict]) -> dict[str, Any]:
    """Exports are counted from the audit log, same as every other metric
    here. Network calls attempted is not: nothing in this codebase has a
    network code path to log one from, so counting it from the audit log
    would be tautological (always 0, from an empty search, not a
    measurement). Reported as a structural guarantee instead, citing the
    two independent checks that actually prove it.
    """
    exports = [e for e in entries if e.get("event") == "export"]
    redacted = sum(1 for e in exports if e.get("redacted"))

    return {
        "definition": (
            "exports_performed/exports_redacted are counted from `export` audit "
            "events; network_calls_attempted is a structural guarantee (see note), "
            "not an audit-log count"
        ),
        "exports_performed": len(exports),
        "exports_redacted": redacted,
        "network_calls_attempted": 0,
        "network_calls_note": (
            "No code path in this system has a network call to attempt. Proven by "
            "host/tests/test_no_network.py: a static AST scan finds no networking "
            "import in any MCP server, and a dynamic socket-patch during a real "
            "question confirms zero non-loopback connections."
        ),
    }


def build_report(entries: list[dict]) -> dict[str, Any]:
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "entries_analyzed": len(entries),
        "hitl_catch_rate": hitl_catch_rate(entries),
        "tool_grounding": tool_grounding(entries),
        "narration_faithfulness": narration_faithfulness(entries),
        "sovereignty_integrity": sovereignty_integrity(entries),
    }
