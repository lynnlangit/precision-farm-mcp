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
    """Raised when a request is rejected and the caller has no fallback.
    Optionally carries the ConfirmationRequest that was rejected, so a
    catcher (e.g. a query-time snapshot loader) can report exactly what's
    unconfirmed rather than just that something is.
    """

    def __init__(self, message: str, request: ConfirmationRequest | None = None):
        super().__init__(message)
        self.request = request


def auto_approve(request: ConfirmationRequest) -> ConfirmationResponse:
    """Approves every proposal as-is. For tests that want to exercise the
    downstream pipeline without exercising the confirm step itself, and for
    farm-ingest's --auto-approve-synthetic-only flag (see ingest_cli.py) --
    that flag is the one real-CLI caller, and it's structurally restricted to
    the example synthetic data directory: DEF-ALIASTIE exists specifically to
    prove auto-approval gives a confidently wrong answer on real data, so
    this must never be reachable outside a demo/workshop data directory.
    """
    return ConfirmationResponse(approved=True, answer=request.proposal)


def refuse_unconfirmed(request: ConfirmationRequest) -> ConfirmationResponse:
    """Always declines. The query-time terminal confirm_fn: an MCP server is a
    non-interactive stdio subprocess and can never prompt a human, so a
    request with no persisted answer must be refused, never guessed -- the
    mirror image of auto_approve, and just as unsafe to use outside its one
    intended context (query-time PersistedConfirm).
    """
    return ConfirmationResponse(approved=False, answer={})


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
    """Prompts on stdin. Used by the ingest CLI; low confidence never
    auto-proceeds even in this path. If PersistedConfirm is re-checking an
    already-confirmed key (a "recheck"/correction run), it stashes the
    previous answer in request.context["previous_confirmed_answer"] -- when
    present, the reviewer is asked to keep, correct, or reject rather than a
    plain yes/no.
    """
    previous = request.context.get("previous_confirmed_answer")
    print(f"\n[confirm] {request.kind}: {request.subject}")
    if previous is not None:
        print(f"  previously confirmed as: {previous}")
        print(f"  new proposal:            {request.proposal}")
        print(f"  confidence: {request.confidence}")
        answer = input("  keep previous / accept new / reject? [k/a/N]: ").strip().lower()
        if answer == "k":
            return ConfirmationResponse(approved=True, answer=previous)
        if answer == "a":
            return ConfirmationResponse(approved=True, answer=request.proposal)
        return _type_in_correction(request)
    print(f"  proposal: {request.proposal}")
    print(f"  confidence: {request.confidence}")
    answer = input("  approve? [y/N]: ").strip().lower()
    if answer == "y":
        return ConfirmationResponse(approved=True, answer=request.proposal)
    return _type_in_correction(request)


def _type_in_correction(request: ConfirmationRequest) -> ConfirmationResponse:
    """Offered whenever a reviewer rejects a naming_drift_alias proposal (both
    a first pass and a recheck): rejecting outright leaves no way to name the
    actually-correct field, and a wrong auto-pick with no path to a right
    answer defeats the point of asking. Blank input is a genuine reject.
    """
    if request.kind != "naming_drift_alias":
        return ConfirmationResponse(approved=False, answer={})
    candidates = request.context.get("string_candidates") or request.context.get(
        "acreage_candidates"
    )
    if candidates:
        print(f"  candidates: {candidates}")
    typed = input("  correct canonical_boundary_name (blank to reject): ").strip()
    if typed:
        return ConfirmationResponse(approved=True, answer={"canonical_boundary_name": typed})
    return ConfirmationResponse(approved=False, answer={})


def _current_version(entry: dict[str, Any]) -> dict[str, Any]:
    return next(v for v in entry["versions"] if v["version"] == entry["current_version"])


class PersistedConfirm:
    """Wraps a confirm_fn with a JSON-file-backed, versioned cache: a request
    already confirmed for this exact key is returned without asking again. A
    new or changed key (different source data) always goes through
    confirm_fn. With recheck=True, already-confirmed keys are re-asked too --
    a correction appends a new version rather than overwriting the old one,
    so the history of what changed and why stays intact.
    """

    def __init__(self, store_path: Path, inner: ConfirmFn, recheck: bool = False):
        self.store_path = store_path
        self.inner = inner
        self.recheck = recheck
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

    def has_key(self, key: str) -> bool:
        return key in self._store["confirmed"]

    def current_answer(self, key: str) -> dict[str, Any] | None:
        entry = self._store["confirmed"].get(key)
        return None if entry is None else _current_version(entry)["answer"]

    def __call__(self, request: ConfirmationRequest) -> ConfirmationResponse:
        entry = self._store["confirmed"].get(request.key)

        if entry is not None and not self.recheck:
            return ConfirmationResponse(approved=True, answer=_current_version(entry)["answer"])

        if entry is not None:
            request = dataclasses.replace(
                request,
                context={
                    **request.context,
                    "previous_confirmed_answer": _current_version(entry)["answer"],
                },
            )

        response = self.inner(request)
        if response.approved:
            self._record(request.key, request.kind, request.subject, response.answer, entry)
            self._save()
        return response

    def _record(
        self, key: str, kind: str, subject: str, answer: dict[str, Any], entry: dict[str, Any] | None
    ) -> None:
        if entry is None:
            self._store["confirmed"][key] = {
                "kind": kind,
                "subject": subject,
                "current_version": 1,
                "versions": [{"version": 1, "answer": answer, "decision": "accepted"}],
            }
            return
        if _current_version(entry)["answer"] == answer:
            return  # re-confirmed the same answer -- not a new version
        next_version = entry["current_version"] + 1
        entry["versions"].append(
            {
                "version": next_version,
                "answer": answer,
                "decision": "corrected",
                "supersedes": entry["current_version"],
            }
        )
        entry["current_version"] = next_version
