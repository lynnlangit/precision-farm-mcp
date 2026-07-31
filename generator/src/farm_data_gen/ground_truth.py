"""Assembles ground_truth.json: the answer key every downstream test and the
eventual POC verify against. Runs a self-consistency check before returning --
if a split/merge's acreage doesn't balance, that's a generator bug, and it must
fail loudly here rather than silently shipping a bad answer key.
"""

from __future__ import annotations

from . import __version__
from .defects import DefectPlan, build_structural_defect_records
from .economics import find_catastrophic_info, find_marginal_field_id
from .farm import FarmModel


def _check_acreage_conservation(farm: FarmModel) -> None:
    for event in farm.identity.events:
        if event.type == "split":
            (parent_id,) = event.parent_field_ids
            parent_acres = farm.acres_by_field[parent_id]
            child_total = sum(farm.acres_by_field[c] for c in event.child_field_ids)
            if abs(parent_acres - child_total) > 0.05:
                raise AssertionError(
                    f"Acreage conservation failed for split {event.event_id}: "
                    f"parent {parent_acres} != children sum {child_total}"
                )
        elif event.type == "merge":
            (child_id,) = event.child_field_ids
            parent_total = sum(farm.acres_by_field[p] for p in event.parent_field_ids)
            child_acres = farm.acres_by_field[child_id]
            if abs(parent_total - child_acres) > 0.05:
                raise AssertionError(
                    f"Acreage conservation failed for merge {event.event_id}: "
                    f"parents sum {parent_total} != child {child_acres}"
                )


def _check_every_defect_has_stable_id(defects: list[dict]) -> None:
    seen: set[str] = set()
    for d in defects:
        defect_id = d.get("defect_id")
        if not defect_id:
            raise AssertionError(f"Defect record missing defect_id: {d}")
        if defect_id in seen:
            raise AssertionError(f"Duplicate defect_id: {defect_id}")
        seen.add(defect_id)


def build_ground_truth(
    farm: FarmModel,
    plan: DefectPlan,
    file_defect_records: list[dict],
) -> dict:
    _check_acreage_conservation(farm)

    defects = list(file_defect_records)
    defects.extend(build_structural_defect_records(farm, plan))
    for event in farm.identity.events:
        defects.append(
            {
                "defect_id": event.event_id,
                "type": event.type,
                "field_id": event.field_id,
                "season": event.effective_season,
                "detail": event.description,
                "expected_detection": (
                    "Field-identity resolution must treat this as a first-class "
                    "event with an effective season, never as unrelated fields."
                ),
                "ground_truth_correction": (
                    "See identity_events for the authoritative parent/child field ids."
                ),
            }
        )

    _check_every_defect_has_stable_id(defects)
    defects.sort(key=lambda d: d["defect_id"])

    profitability: dict[str, dict[str, dict]] = {}
    for (field_id, season), record in farm.records.items():
        profitability.setdefault(field_id, {})[str(season)] = {
            "revenue": record.revenue,
            "costs": record.total_cost,
            "profit": record.profit,
            "profit_per_acre": record.profit_per_acre,
            "acres": record.acres,
            "crop": record.crop,
            "yield_source_used": "scale_tickets",
            "cost_basis": "per_acre",
            "reasoning": record.reasoning(),
        }

    canonical_fields = {}
    for field_id, field in farm.identity.canonical_fields.items():
        canonical_fields[field_id] = {
            "display_name_by_season": {
                str(s): n for s, n in sorted(field.display_name_by_season.items())
            },
            "acres_by_season": {
                str(s): farm.acres_by_field[field_id] for s in field.active_seasons
            },
            "crop_by_season": {str(s): farm.record(field_id, s).crop for s in field.active_seasons},
            "active_seasons": field.active_seasons,
            "role": field.role,
        }

    config = farm.config
    return {
        "generator": {
            "seed": config.random_seed,
            "num_fields": config.num_fields,
            "seasons": config.seasons,
            "version": __version__,
        },
        "canonical_fields": canonical_fields,
        "identity_events": [e.to_json() for e in farm.identity.events],
        "profitability": profitability,
        "defects": defects,
        "marginal_field_id": find_marginal_field_id(farm.identity),
        "catastrophic_year": find_catastrophic_info(farm.identity, farm.records),
        "weathershortfall": farm.weathershortfall,
        "mgmtshortfall": farm.mgmtshortfall,
        "bad_zone": plan.bad_zone,
    }
