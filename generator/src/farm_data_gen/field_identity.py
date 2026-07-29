"""Field identity: canonical fields, the alias table, and the split/merge/rename/
drop event graph.

The farmer's field name is the primary key from the farmer's point of view, but
names drift, get reassigned at rename time, and stop meaning anything after a
split or merge. So internally every distinct parcel-history gets a stable
canonical_id that never appears in any raw output file (GeoJSON/CSV/XLSX) -- only
in ground_truth.json. The raw files only ever carry the farmer-visible name as of
that season, drift and all. Resolving name -> canonical_id from messy names alone
is the problem the eventual POC has to solve; the generator must not leak the
shortcut.

Roles are assigned to fixed root-field indices (not chosen by the RNG) so that
every one of the four required identity events, the naming-drift field, the
marginal field, and the catastrophic-year field are always present regardless of
seed. The RNG governs quantities (acreage, yields, prices) layered on top of this
fixed structure, in rng-derived modules downstream.
"""

from __future__ import annotations

import dataclasses

from . import rng as rng_mod
from .config import SimConfig

CORN = "corn"
SOYBEAN = "soybean"

MIN_FIELDS_FOR_REQUIRED_ROLES = 10
MIN_SEASONS_FOR_REQUIRED_EVENTS = 6
_REFERENCE_NUM_SEASONS = 10  # the season count the default *_index config values assume

# Fixed root-field roster. Index is the structural identity; name is flavor.
# role values: "split", "merge_a", "merge_b", "rename", "rental_lost",
# "naming_drift", "marginal", "catastrophic", "continuous_corn", "normal"
# Every entry here is load-bearing for a mandatory defect/role -- this is the
# minimum roster (10 fields) required regardless of --fields. "normal" filler
# fields beyond this are added separately, only once num_fields > 10.
_REQUIRED_ROSTER: list[tuple[str, str, str]] = [
    ("root_01", "West 120", "continuous_corn"),
    ("root_02", "East 80", "catastrophic"),
    ("root_04", "N 80", "naming_drift"),
    ("root_05", "South 160", "split"),
    ("root_06", "River Bottom", "rename"),
    ("root_07", "Elevator Forty", "merge_a"),
    ("root_08", "Depot Forty", "merge_b"),
    ("root_09", "Township Rd 12", "rental_lost"),
    ("root_10", "Marginal Eighty", "marginal"),
    ("root_11", "Coulee Field", "continuous_corn"),
]

# Named filler fields used before falling back to _make_extra_name.
_FILLER_ROSTER: list[tuple[str, str, str]] = [
    ("root_03", "Home Quarter", "normal"),
    ("root_12", "Section Corner", "normal"),
]

_NAMING_DRIFT_VARIANTS = ["N 80", "north eighty", "North 80", "N80"]

_EXTRA_FIELD_BASE_NAMES = [
    "Grain Bin Quarter",
    "Windbreak Forty",
    "Slough Eighty",
    "Rail Line Sixty",
    "Section 14",
    "Old Homestead",
    "Prairie Rose Quarter",
    "Ditch Bank Forty",
]


@dataclasses.dataclass
class IdentityEvent:
    event_id: str
    type: str  # "split" | "merge" | "rename" | "rental_lost"
    effective_season: int
    parent_field_ids: list[str] = dataclasses.field(default_factory=list)
    child_field_ids: list[str] = dataclasses.field(default_factory=list)
    field_id: str | None = None
    old_name: str | None = None
    new_name: str | None = None
    last_season_present: int | None = None
    description: str = ""

    def to_json(self) -> dict:
        d = {
            "event_id": self.event_id,
            "type": self.type,
            "effective_season": self.effective_season,
        }
        if self.parent_field_ids:
            d["parent_field_ids"] = self.parent_field_ids
        if self.child_field_ids:
            d["child_field_ids"] = self.child_field_ids
        if self.field_id:
            d["field_id"] = self.field_id
        if self.old_name:
            d["old_name"] = self.old_name
        if self.new_name:
            d["new_name"] = self.new_name
        if self.last_season_present is not None:
            d["last_season_present"] = self.last_season_present
        if self.description:
            d["description"] = self.description
        return d


@dataclasses.dataclass
class CanonicalField:
    field_id: str
    role: str
    is_continuous_corn: bool
    active_seasons: list[int]
    display_name_by_season: dict[int, str]
    spreadsheet_alias_by_season: dict[int, str]
    rotation_phase: int
    lineage_note: str = ""


@dataclasses.dataclass
class FarmIdentity:
    config: SimConfig
    canonical_fields: dict[str, CanonicalField]
    events: list[IdentityEvent]

    def active_field_ids(self, season: int) -> list[str]:
        return sorted(fid for fid, f in self.canonical_fields.items() if season in f.active_seasons)

    def to_json(self) -> dict:
        return {
            "canonical_fields": {
                fid: {
                    "display_name_by_season": {
                        str(s): n for s, n in sorted(f.display_name_by_season.items())
                    },
                    "active_seasons": f.active_seasons,
                }
                for fid, f in sorted(self.canonical_fields.items())
            },
            "identity_events": [e.to_json() for e in self.events],
        }


def _make_extra_name(index: int, seed: int) -> str:
    r = rng_mod.derive_rng(seed, "extra_field_name", index)
    base = _EXTRA_FIELD_BASE_NAMES[index % len(_EXTRA_FIELD_BASE_NAMES)]
    suffix = int(r.integers(1, 99))
    return f"{base} {suffix}" if index >= len(_EXTRA_FIELD_BASE_NAMES) else base


def scaled_indices(config: SimConfig, num_seasons: int) -> dict[str, int]:
    """The default *_index fields on SimConfig assume a 10-season run. Rescale
    them proportionally for other --seasons values, then nudge into strictly
    increasing order so split < rename < merge < missing-swath never collide
    even at the minimum supported season count.
    """
    raw = {
        "split": config.split_season_index,
        "rename": config.rename_season_index,
        "merge": config.merge_season_index,
        "missing_swath": config.missing_swath_season_index,
    }
    last = -1
    scaled: dict[str, int] = {}
    for key, base_index in raw.items():
        idx = round(base_index / (_REFERENCE_NUM_SEASONS - 1) * (num_seasons - 1))
        idx = max(idx, last + 1)
        idx = min(idx, num_seasons - 1)
        scaled[key] = idx
        last = idx
    return scaled


def build_field_identity(config: SimConfig) -> FarmIdentity:
    if config.num_fields < MIN_FIELDS_FOR_REQUIRED_ROLES:
        raise ValueError(
            f"num_fields={config.num_fields} is too small: at least "
            f"{MIN_FIELDS_FOR_REQUIRED_ROLES} fields are required to host every "
            "mandatory identity event and defect role."
        )
    if config.num_seasons < MIN_SEASONS_FOR_REQUIRED_EVENTS:
        raise ValueError(
            f"num_seasons={config.num_seasons} is too small: at least "
            f"{MIN_SEASONS_FOR_REQUIRED_EVENTS} seasons are required so split/rename/"
            "merge/rental-lost events stay distinct and ordered."
        )

    seasons = config.seasons
    indices = scaled_indices(config, len(seasons))
    split_season = seasons[indices["split"]]
    merge_season = seasons[indices["merge"]]
    rename_season = seasons[indices["rename"]]
    rental_lost_index = min(config.rental_lost_last_season_index, len(seasons) - 2)
    rental_lost_last_season = seasons[rental_lost_index]

    roster = list(_REQUIRED_ROSTER)
    num_filler_needed = config.num_fields - len(_REQUIRED_ROSTER)
    roster.extend(_FILLER_ROSTER[:num_filler_needed])
    for extra_i in range(num_filler_needed - len(_FILLER_ROSTER)):
        name = _make_extra_name(extra_i, config.random_seed)
        roster.append((f"root_extra_{extra_i:02d}", name, "normal"))

    canonical_fields: dict[str, CanonicalField] = {}
    events: list[IdentityEvent] = []

    for phase, (root_id, root_name, role) in enumerate(roster):
        is_continuous_corn = role == "continuous_corn"

        if role == "split":
            pre_seasons = [s for s in seasons if s < split_season]
            child_a_id, child_b_id = f"{root_id}_a", f"{root_id}_b"
            post_seasons = [s for s in seasons if s >= split_season]
            canonical_fields[root_id] = CanonicalField(
                field_id=root_id,
                role="split_parent",
                is_continuous_corn=False,
                active_seasons=pre_seasons,
                display_name_by_season={s: root_name for s in pre_seasons},
                spreadsheet_alias_by_season={s: root_name for s in pre_seasons},
                rotation_phase=phase,
            )
            child_a_name = f"{root_name} North"
            child_b_name = f"{root_name} South"
            canonical_fields[child_a_id] = CanonicalField(
                field_id=child_a_id,
                role="split_child",
                is_continuous_corn=False,
                active_seasons=post_seasons,
                display_name_by_season={s: child_a_name for s in post_seasons},
                spreadsheet_alias_by_season={s: child_a_name for s in post_seasons},
                rotation_phase=phase,
                lineage_note=f"split from {root_id}",
            )
            canonical_fields[child_b_id] = CanonicalField(
                field_id=child_b_id,
                role="split_child",
                is_continuous_corn=False,
                active_seasons=post_seasons,
                display_name_by_season={s: child_b_name for s in post_seasons},
                spreadsheet_alias_by_season={s: child_b_name for s in post_seasons},
                rotation_phase=phase + 100,
                lineage_note=f"split from {root_id}",
            )
            events.append(
                IdentityEvent(
                    event_id=f"evt_split_{root_id}",
                    type="split",
                    effective_season=split_season,
                    parent_field_ids=[root_id],
                    child_field_ids=[child_a_id, child_b_id],
                    description=(
                        f"{root_name} split into {child_a_name} and {child_b_name} "
                        f"starting season {split_season}."
                    ),
                )
            )
            continue

        if role == "merge_a":
            partner_root_id, partner_name, _ = next(r for r in roster if r[2] == "merge_b")
            pre_seasons = [s for s in seasons if s < merge_season]
            canonical_fields[root_id] = CanonicalField(
                field_id=root_id,
                role="merge_parent",
                is_continuous_corn=False,
                active_seasons=pre_seasons,
                display_name_by_season={s: root_name for s in pre_seasons},
                spreadsheet_alias_by_season={s: root_name for s in pre_seasons},
                rotation_phase=phase,
            )
            merged_id = f"{root_id}_{partner_root_id}_merged"
            merged_name = f"{root_name}-{partner_name}"
            post_seasons = [s for s in seasons if s >= merge_season]
            canonical_fields[merged_id] = CanonicalField(
                field_id=merged_id,
                role="merge_child",
                is_continuous_corn=False,
                active_seasons=post_seasons,
                display_name_by_season={s: merged_name for s in post_seasons},
                spreadsheet_alias_by_season={s: merged_name for s in post_seasons},
                rotation_phase=phase,
                lineage_note=f"merged from {root_id} + {partner_root_id}",
            )
            events.append(
                IdentityEvent(
                    event_id=f"evt_merge_{root_id}_{partner_root_id}",
                    type="merge",
                    effective_season=merge_season,
                    parent_field_ids=[root_id, partner_root_id],
                    child_field_ids=[merged_id],
                    description=(
                        f"{root_name} and {partner_name} merged into {merged_name} "
                        f"starting season {merge_season}."
                    ),
                )
            )
            continue

        if role == "merge_b":
            pre_seasons = [s for s in seasons if s < merge_season]
            canonical_fields[root_id] = CanonicalField(
                field_id=root_id,
                role="merge_parent",
                is_continuous_corn=False,
                active_seasons=pre_seasons,
                display_name_by_season={s: root_name for s in pre_seasons},
                spreadsheet_alias_by_season={s: root_name for s in pre_seasons},
                rotation_phase=phase,
            )
            continue

        if role == "rename":
            old_name = root_name
            new_name = f"Riverside"  # noqa: F541 (deliberate: explicit final name)
            names = {s: (old_name if s < rename_season else new_name) for s in seasons}
            canonical_fields[root_id] = CanonicalField(
                field_id=root_id,
                role="rename",
                is_continuous_corn=False,
                active_seasons=list(seasons),
                display_name_by_season=names,
                spreadsheet_alias_by_season=dict(names),
                rotation_phase=phase,
            )
            events.append(
                IdentityEvent(
                    event_id=f"evt_rename_{root_id}",
                    type="rename",
                    effective_season=rename_season,
                    field_id=root_id,
                    old_name=old_name,
                    new_name=new_name,
                    description=(
                        f"Farmer renamed {old_name} to {new_name} starting season "
                        f"{rename_season}; it is the same ground."
                    ),
                )
            )
            continue

        if role == "rental_lost":
            active_seasons = [s for s in seasons if s <= rental_lost_last_season]
            canonical_fields[root_id] = CanonicalField(
                field_id=root_id,
                role="rental_lost",
                is_continuous_corn=False,
                active_seasons=active_seasons,
                display_name_by_season={s: root_name for s in active_seasons},
                spreadsheet_alias_by_season={s: root_name for s in active_seasons},
                rotation_phase=phase,
            )
            events.append(
                IdentityEvent(
                    event_id=f"evt_rental_lost_{root_id}",
                    type="rental_lost",
                    effective_season=seasons[
                        min(config.rental_lost_last_season_index + 1, len(seasons) - 1)
                    ],
                    field_id=root_id,
                    last_season_present=rental_lost_last_season,
                    description=(
                        f"{root_name} was rented ground; lease ended after season "
                        f"{rental_lost_last_season}. No boundary exists thereafter."
                    ),
                )
            )
            continue

        if role == "naming_drift":
            names = {
                s: _NAMING_DRIFT_VARIANTS[i % len(_NAMING_DRIFT_VARIANTS)]
                for i, s in enumerate(seasons)
            }
            canonical_fields[root_id] = CanonicalField(
                field_id=root_id,
                role="naming_drift",
                is_continuous_corn=False,
                active_seasons=list(seasons),
                display_name_by_season={s: root_name for s in seasons},
                spreadsheet_alias_by_season=names,
                rotation_phase=phase,
            )
            continue

        # normal / marginal / catastrophic / continuous_corn: no identity events
        canonical_fields[root_id] = CanonicalField(
            field_id=root_id,
            role=role,
            is_continuous_corn=is_continuous_corn,
            active_seasons=list(seasons),
            display_name_by_season={s: root_name for s in seasons},
            spreadsheet_alias_by_season={s: root_name for s in seasons},
            rotation_phase=phase,
        )

    identity = FarmIdentity(config=config, canonical_fields=canonical_fields, events=events)
    _validate_acreage_conservation(identity)
    return identity


def _validate_acreage_conservation(identity: FarmIdentity) -> None:
    """Self-check placeholder; the real acreage check runs once acreage is
    assigned in farm.py (split/merge acreage must balance). Here we only check
    that every event's parent/child ids actually exist in canonical_fields.
    """
    for event in identity.events:
        for fid in (*event.parent_field_ids, *event.child_field_ids, event.field_id or ""):
            if fid and fid not in identity.canonical_fields:
                raise ValueError(f"Identity event {event.event_id} references unknown field {fid}")
