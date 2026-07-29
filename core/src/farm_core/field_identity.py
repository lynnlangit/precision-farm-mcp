"""Resolve the canonical 10-year field timeline from raw boundary files alone.

The boundary files carry only a farmer-visible name per season -- no canonical
ID, by design (see generator/). Season-to-season, a name can: continue
unchanged, get formally renamed, split into two, merge with another, or drop
out of the record with no successor (lost rental ground). Distinguishing these
from a plain "name changed" requires a signal that survives all of them:
acreage. A continuing field's acreage is exactly stable; a split's two
children sum to the parent's; a merge's parent acreages sum to the child's.
String similarity is not used here at all -- it's the wrong tool for this
half of the problem (see alias_resolution.py for where it legitimately
applies, and why acreage still wins there too).

Every non-trivial match (anything but an unchanged name) is a
ConfirmationRequest, never resolved silently.
"""

from __future__ import annotations

import dataclasses
import itertools

import duckdb

from . import confirm as confirm_mod

ACRES_TOLERANCE = 0.1


@dataclasses.dataclass
class Lineage:
    canonical_id: str
    display_name_by_season: dict[int, str] = dataclasses.field(default_factory=dict)
    active_seasons: list[int] = dataclasses.field(default_factory=list)
    ended: bool = False


@dataclasses.dataclass(frozen=True)
class IdentityEvent:
    type: str  # "rename" | "split" | "merge" | "rental_lost"
    effective_season: int
    old_name: str | None = None
    new_name: str | None = None
    parent_names: tuple[str, ...] = ()
    child_names: tuple[str, ...] = ()
    last_season_present: int | None = None

    def to_json(self) -> dict:
        d: dict = {"type": self.type, "effective_season": self.effective_season}
        if self.old_name:
            d["old_name"] = self.old_name
        if self.new_name:
            d["new_name"] = self.new_name
        if self.parent_names:
            d["parent_names"] = list(self.parent_names)
        if self.child_names:
            d["child_names"] = list(self.child_names)
        if self.last_season_present is not None:
            d["last_season_present"] = self.last_season_present
        return d


@dataclasses.dataclass
class FieldIdentityResolution:
    lineages: dict[str, Lineage]
    events: list[IdentityEvent]

    def to_json(self) -> dict:
        return {
            "canonical_fields": {
                cid: {
                    "display_name_by_season": {
                        str(s): n for s, n in sorted(lineage.display_name_by_season.items())
                    },
                    "active_seasons": lineage.active_seasons,
                }
                for cid, lineage in sorted(self.lineages.items())
            },
            "identity_events": [e.to_json() for e in self.events],
        }


def _season_names_acres(con: duckdb.DuckDBPyConnection, season: int) -> dict[str, float]:
    rows = con.execute(
        "SELECT field_name, acres FROM boundary_fields WHERE season = ?", [season]
    ).fetchall()
    return dict(rows)


def _match_transition(
    disappeared: dict[str, float], appeared: dict[str, float]
) -> list[tuple[str, list[tuple[str, float]]]]:
    """Greedily decompose a transition into (kind, disappeared_names, appeared_names)
    groups using acreage-sum matching. Returns a list of
    (kind, [(name, role)]) tuples -- kind in {"rename","split","merge","rental_lost"}.
    Mutates nothing; returns fully resolved groupings plus leftovers as
    "rental_lost" (disappeared with no match).
    """
    remaining_d = dict(disappeared)
    remaining_a = dict(appeared)
    groups: list[tuple[str, dict[str, float], dict[str, float]]] = []

    # 1:1 rename -- exact acreage match
    for d_name, d_acres in list(remaining_d.items()):
        for a_name, a_acres in list(remaining_a.items()):
            if abs(d_acres - a_acres) <= ACRES_TOLERANCE:
                groups.append(("rename", {d_name: d_acres}, {a_name: a_acres}))
                del remaining_d[d_name]
                del remaining_a[a_name]
                break

    # split -- 1 disappeared, 2 appeared summing to it
    for d_name, d_acres in list(remaining_d.items()):
        for combo in itertools.combinations(remaining_a.items(), 2):
            (a1, ac1), (a2, ac2) = combo
            if abs((ac1 + ac2) - d_acres) <= ACRES_TOLERANCE:
                groups.append(("split", {d_name: d_acres}, {a1: ac1, a2: ac2}))
                del remaining_d[d_name]
                del remaining_a[a1]
                del remaining_a[a2]
                break

    # merge -- 2 disappeared summing to 1 appeared
    for a_name, a_acres in list(remaining_a.items()):
        for combo in itertools.combinations(remaining_d.items(), 2):
            (d1, dc1), (d2, dc2) = combo
            if abs((dc1 + dc2) - a_acres) <= ACRES_TOLERANCE:
                groups.append(("merge", {d1: dc1, d2: dc2}, {a_name: a_acres}))
                del remaining_a[a_name]
                del remaining_d[d1]
                del remaining_d[d2]
                break

    for d_name, d_acres in remaining_d.items():
        groups.append(("rental_lost", {d_name: d_acres}, {}))
    for a_name, a_acres in remaining_a.items():
        groups.append(("unexplained_new_field", {}, {a_name: a_acres}))

    return groups


def _confirm_group(
    confirm_fn: confirm_mod.ConfirmFn, season: int, next_season: int, kind: str, d: dict, a: dict
) -> tuple[confirm_mod.ConfirmationRequest, confirm_mod.ConfirmationResponse]:
    proposal = {"type": kind}
    if kind == "rename":
        proposal.update(old_name=next(iter(d)), new_name=next(iter(a)))
    elif kind == "split":
        proposal.update(parent_name=next(iter(d)), child_names=sorted(a))
    elif kind == "merge":
        proposal.update(parent_names=sorted(d), child_name=next(iter(a)))
    elif kind == "rental_lost":
        proposal.update(field_name=next(iter(d)), last_season_present=season)
    else:
        proposal.update(field_name=next(iter(a)))

    request = confirm_mod.ConfirmationRequest(
        kind="identity_event",
        key=f"identity:{season}->{next_season}:{kind}:{sorted(d)}:{sorted(a)}",
        subject=f"{kind} between season {season} and {next_season}: {sorted(d)} -> {sorted(a)}",
        proposal=proposal,
        confidence="high",
        context={"disappeared_acres": d, "appeared_acres": a},
    )
    return request, confirm_fn(request)


def resolve_field_identity(
    con: duckdb.DuckDBPyConnection, seasons: list[int], confirm_fn: confirm_mod.ConfirmFn
) -> FieldIdentityResolution:
    seasons = sorted(seasons)
    lineages: dict[str, Lineage] = {}
    events: list[IdentityEvent] = []
    active_lineage_by_name: dict[str, str] = {}
    next_id = itertools.count(1)

    def new_lineage(name: str, season: int) -> str:
        cid = f"resolved_{next(next_id):04d}"
        lineages[cid] = Lineage(canonical_id=cid)
        active_lineage_by_name[name] = cid
        return cid

    first_names = _season_names_acres(con, seasons[0])
    for name in first_names:
        cid = new_lineage(name, seasons[0])
        lineages[cid].display_name_by_season[seasons[0]] = name
        lineages[cid].active_seasons.append(seasons[0])

    for season, next_season in zip(seasons, seasons[1:]):
        names_now = _season_names_acres(con, season)
        names_next = _season_names_acres(con, next_season)

        disappeared = {n: a for n, a in names_now.items() if n not in names_next}
        appeared = {n: a for n, a in names_next.items() if n not in names_now}
        continuing = set(names_now) & set(names_next)

        for name in continuing:
            cid = active_lineage_by_name[name]
            lineages[cid].display_name_by_season[next_season] = name
            lineages[cid].active_seasons.append(next_season)

        for kind, d, a in _match_transition(disappeared, appeared):
            request, response = _confirm_group(confirm_fn, season, next_season, kind, d, a)
            if not response.approved:
                raise confirm_mod.ConfirmationRejected(
                    f"Identity event {kind} at {season}->{next_season} ({d} -> {a}) "
                    "was not confirmed",
                    request=request,
                )
            answer = response.answer

            if kind == "rename":
                old_name, new_name = next(iter(d)), next(iter(a))
                cid = active_lineage_by_name.pop(old_name)
                lineages[cid].display_name_by_season[next_season] = new_name
                lineages[cid].active_seasons.append(next_season)
                active_lineage_by_name[new_name] = cid
                events.append(
                    IdentityEvent(
                        type="rename",
                        effective_season=next_season,
                        old_name=answer.get("old_name", old_name),
                        new_name=answer.get("new_name", new_name),
                    )
                )

            elif kind == "split":
                parent_name = next(iter(d))
                child_names = sorted(a)
                parent_cid = active_lineage_by_name.pop(parent_name)
                lineages[parent_cid].ended = True
                for child_name in child_names:
                    child_cid = new_lineage(child_name, next_season)
                    lineages[child_cid].display_name_by_season[next_season] = child_name
                    lineages[child_cid].active_seasons.append(next_season)
                events.append(
                    IdentityEvent(
                        type="split",
                        effective_season=next_season,
                        parent_names=(parent_name,),
                        child_names=tuple(child_names),
                    )
                )

            elif kind == "merge":
                parent_names = sorted(d)
                child_name = next(iter(a))
                for p in parent_names:
                    lineages[active_lineage_by_name.pop(p)].ended = True
                child_cid = new_lineage(child_name, next_season)
                lineages[child_cid].display_name_by_season[next_season] = child_name
                lineages[child_cid].active_seasons.append(next_season)
                events.append(
                    IdentityEvent(
                        type="merge",
                        effective_season=next_season,
                        parent_names=tuple(parent_names),
                        child_names=(child_name,),
                    )
                )

            elif kind == "rental_lost":
                field_name = next(iter(d))
                cid = active_lineage_by_name.pop(field_name)
                lineages[cid].ended = True
                events.append(
                    IdentityEvent(
                        type="rental_lost",
                        effective_season=next_season,
                        old_name=field_name,
                        last_season_present=season,
                    )
                )

            else:  # unexplained_new_field
                new_name = next(iter(a))
                new_lineage(new_name, next_season)
                lineages[active_lineage_by_name[new_name]].display_name_by_season[next_season] = (
                    new_name
                )
                lineages[active_lineage_by_name[new_name]].active_seasons.append(next_season)

    return FieldIdentityResolution(lineages=lineages, events=events)
