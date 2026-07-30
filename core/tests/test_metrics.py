"""Phase B / B1 verification: each governance metric's math, against
hand-built audit-log-shaped fixtures -- fast, deterministic, no live
services. `AuditLog.entries()` returns plain dicts with an "event" key plus
whatever kwargs were logged; these fixtures only need the fields each
metric actually reads.
"""

from farm_core.metrics import (
    build_report,
    hitl_catch_rate,
    narration_faithfulness,
    sovereignty_integrity,
    tool_grounding,
)


def test_hitl_catch_rate_computes_correctly():
    entries = (
        [{"event": "confirmation_accepted"}] * 3
        + [{"event": "confirmation_corrected"}] * 2
        + [{"event": "confirmation_refused"}] * 1
    )
    result = hitl_catch_rate(entries)
    assert result["accepted"] == 3
    assert result["corrected"] == 2
    assert result["refused"] == 1
    assert result["rate"] == 0.5


def test_hitl_catch_rate_is_null_with_no_confirmation_decisions():
    result = hitl_catch_rate([{"event": "query", "question": "x"}])
    assert result["rate"] is None
    assert result["accepted"] == result["corrected"] == result["refused"] == 0


def test_hitl_catch_rate_ignores_non_confirmation_events():
    entries = [
        {"event": "confirmation_accepted"},
        {"event": "tool_call", "tool": "x"},
        {"event": "narration", "question": "x"},
    ]
    result = hitl_catch_rate(entries)
    assert result["accepted"] == 1
    assert result["rate"] == 0.0  # 0 corrected/refused out of 1 total


def test_tool_grounding_measured_or_derived_rate():
    entries = [
        {"event": "narration", "grounded": True, "modeled_grounded": None},
        {"event": "narration", "grounded": True, "modeled_grounded": None},
        {"event": "narration", "grounded": False, "modeled_grounded": None},
    ]
    result = tool_grounding(entries)
    assert result["narrations_analyzed"] == 3
    assert result["measured_or_derived_rate"] == round(2 / 3, 4)


def test_tool_grounding_modeled_rate_is_null_with_no_modeled_data():
    entries = [{"event": "narration", "grounded": True, "modeled_grounded": None}]
    result = tool_grounding(entries)
    assert result["narrations_with_modeled_data"] == 0
    assert result["modeled_rate"] is None


def test_tool_grounding_modeled_rate_when_present():
    entries = [
        {"event": "narration", "grounded": True, "modeled_grounded": True},
        {"event": "narration", "grounded": True, "modeled_grounded": False},
        {"event": "narration", "grounded": True, "modeled_grounded": None},
    ]
    result = tool_grounding(entries)
    assert result["narrations_with_modeled_data"] == 2
    assert result["modeled_rate"] == 0.5


def test_legacy_narration_events_missing_new_fields_are_excluded_not_crashed():
    """Narration events logged before this module existed only have
    "question" -- they must be excluded from the analyzed count, not
    treated as ungrounded or cause a KeyError.
    """
    entries = [
        {"event": "narration", "question": "was the north eighty a bad field"},
        {"event": "narration", "grounded": True, "modeled_grounded": None},
    ]
    grounding = tool_grounding(entries)
    assert grounding["narrations_analyzed"] == 1
    assert grounding["measured_or_derived_rate"] == 1.0

    faithfulness = narration_faithfulness(entries)
    assert faithfulness["narrations_analyzed"] == 0
    assert faithfulness["first_attempt_rate"] is None


def test_narration_faithfulness():
    entries = [
        {"event": "narration", "attempts": 1, "used_fallback": False},
        {"event": "narration", "attempts": 1, "used_fallback": False},
        {"event": "narration", "attempts": 2, "used_fallback": False},
        {"event": "narration", "attempts": 2, "used_fallback": True},
    ]
    result = narration_faithfulness(entries)
    assert result["narrations_analyzed"] == 4
    assert result["first_attempt_rate"] == 0.5
    assert result["fallback_rate"] == 0.25


def test_sovereignty_integrity():
    entries = [
        {"event": "export", "redacted": True},
        {"event": "export", "redacted": True},
        {"event": "export", "redacted": False},
        {"event": "tool_call"},
    ]
    result = sovereignty_integrity(entries)
    assert result["exports_performed"] == 3
    assert result["exports_redacted"] == 2
    assert result["network_calls_attempted"] == 0


def test_sovereignty_integrity_with_no_exports():
    result = sovereignty_integrity([])
    assert result["exports_performed"] == 0
    assert result["exports_redacted"] == 0
    assert result["network_calls_attempted"] == 0


def test_build_report_shape():
    report = build_report([{"event": "confirmation_accepted"}])
    assert set(report) == {
        "generated_at",
        "entries_analyzed",
        "hitl_catch_rate",
        "tool_grounding",
        "narration_faithfulness",
        "sovereignty_integrity",
    }
    assert report["entries_analyzed"] == 1
