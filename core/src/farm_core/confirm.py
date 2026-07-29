"""Shared propose/confirm abstraction. Nothing in farm_core resolves an
ambiguous match on its own -- every low-confidence guess (a naming-drift
alias, a split/merge/rename hypothesis, a column mapping) becomes a
ConfirmationRequest that must go through a confirm_fn. A confirmed answer is
persisted and reused on the next ingest of the same input; a changed input
gets a fresh request rather than silently reusing a stale answer.

This is the single choke point enforcing "never resolve a match without
confirmation" -- callers inject a confirm_fn rather than resolving inline, so
the policy can't be bypassed by a shortcut buried in one module.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Callable

CONFIRM_FORMAT_VERSION = 1


@dataclasses.dataclass(frozen=True)
class ConfirmationRequest:
    kind: str  # e.g. "naming_drift_alias", "identity_event", "column_mapping"
    key: str  # stable identity for persistence, e.g. "alias:cost_ledger.xlsx::2019:N80"
    subject: str  # short human-readable description of what's being asked
    proposal: dict[str, Any]  # the proposed structured answer
    confidence: str  # "high" | "low"
    context: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class ConfirmationResponse:
    approved: bool
    answer: dict[str, Any]  # the confirmed (possibly corrected) structured answer
    reviewer_note: str = ""


ConfirmFn = Callable[[ConfirmationRequest], ConfirmationResponse]


class ConfirmationRejected(Exception):
    """Raised when a request is rejected and the caller has no fallback."""


def auto_approve(request: ConfirmationRequest) -> ConfirmationResponse:
    """Approves every proposal as-is. Only for tests that want to exercise the
    downstream pipeline without exercising the confirm step itself -- never
    wire this into the real CLI path.
    """
    return ConfirmationResponse(approved=True, answer=request.proposal)


def fixture_confirm(fixture: dict[str, dict[str, Any]]) -> ConfirmFn:
    """Deterministic confirm_fn for automated tests: looks up request.key in a
    pre-supplied answer table. Raises if a request isn't covered, rather than
    guessing -- an uncovered request means the test fixture is out of date
    with the generator, not that the algorithm should improvise.
    """

    def _confirm(request: ConfirmationRequest) -> ConfirmationResponse:
        if request.key not in fixture:
            raise ConfirmationRejected(
                f"No fixture answer for confirmation request {request.key!r} "
                f"({request.kind}: {request.subject}); update the test fixture."
            )
        return ConfirmationResponse(approved=True, answer=fixture[request.key])

    return _confirm


def interactive_confirm(request: ConfirmationRequest) -> ConfirmationResponse:
    """Prompts on stdin. Used by the real CLI (Phase 6); low confidence never
    auto-proceeds even in this path.
    """
    print(f"\n[confirm] {request.kind}: {request.subject}")
    print(f"  proposal: {request.proposal}")
    print(f"  confidence: {request.confidence}")
    answer = input("  approve? [y/N]: ").strip().lower()
    if answer == "y":
        return ConfirmationResponse(approved=True, answer=request.proposal)
    return ConfirmationResponse(approved=False, answer={})


class PersistedConfirm:
    """Wraps a confirm_fn with a JSON-file-backed cache: a request already
    confirmed for this exact key is returned without asking again. A new or
    changed key (different source data) always goes through confirm_fn.
    """

    def __init__(self, store_path: Path, inner: ConfirmFn):
        self.store_path = store_path
        self.inner = inner
        self._store: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.store_path.exists():
            return json.loads(self.store_path.read_text(encoding="utf-8"))
        return {"version": CONFIRM_FORMAT_VERSION, "confirmed": {}}

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            json.dumps(self._store, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def __call__(self, request: ConfirmationRequest) -> ConfirmationResponse:
        cached = self._store["confirmed"].get(request.key)
        if cached is not None:
            return ConfirmationResponse(approved=True, answer=cached["answer"])

        response = self.inner(request)
        if response.approved:
            self._store["confirmed"][request.key] = {
                "kind": request.kind,
                "subject": request.subject,
                "answer": response.answer,
            }
            self._save()
        return response
