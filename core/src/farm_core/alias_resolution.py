"""Resolve cost-ledger field names (which drift in spelling) to the stable
boundary field name for that season.

Acreage, not string similarity, is the primary signal: a field's acreage is
constant across everything but a split/merge/rename event, so within one
season it's close to a unique fingerprint. String similarity alone is a trap
here -- "Marginal Eighty" and "north eighty" share the literal word "eighty"
and would out-score the correct match "N 80" on text similarity alone. Every
non-exact match still goes through confirmation regardless of how confident
the acreage match looks.
"""

from __future__ import annotations

import dataclasses
import difflib

import duckdb

from . import confirm as confirm_mod

ACRES_ROUND_DP = 1


@dataclasses.dataclass(frozen=True)
class ResolvedAlias:
    season: int
    raw_field_name: str
    canonical_boundary_name: str
    method: str  # "exact" | "acreage_match" | "ambiguous_match"


def _string_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def resolve_season_aliases(
    con: duckdb.DuckDBPyConnection, season: int, confirm_fn: confirm_mod.ConfirmFn
) -> list[ResolvedAlias]:
    boundary_rows = con.execute(
        "SELECT field_name, acres FROM boundary_fields WHERE season = ?", [season]
    ).fetchall()
    boundary_acres_by_name = dict(boundary_rows)
    names_by_acres: dict[float, list[str]] = {}
    for name, acres in boundary_rows:
        names_by_acres.setdefault(round(acres, ACRES_ROUND_DP), []).append(name)

    ledger_rows = con.execute(
        "SELECT raw_field_name, acres FROM cost_ledger_field_names WHERE season = ? "
        "ORDER BY row_index",
        [season],
    ).fetchall()

    resolved: list[ResolvedAlias] = []
    for raw_name, raw_acres in ledger_rows:
        if raw_name in boundary_acres_by_name:
            resolved.append(ResolvedAlias(season, raw_name, raw_name, "exact"))
            continue

        acreage_candidates = names_by_acres.get(round(raw_acres, ACRES_ROUND_DP), [])

        if len(acreage_candidates) == 1:
            canonical = acreage_candidates[0]
            similarity = _string_similarity(raw_name, canonical)
            request = confirm_mod.ConfirmationRequest(
                kind="naming_drift_alias",
                key=f"alias:{season}:{raw_name}",
                subject=f"Cost ledger name {raw_name!r} in season {season}",
                proposal={"canonical_boundary_name": canonical},
                confidence="high" if similarity > 0.3 else "low",
                context={
                    "ledger_acres": raw_acres,
                    "acreage_candidates": acreage_candidates,
                    "string_similarity": round(similarity, 3),
                },
            )
            method = "acreage_match"
        else:
            all_names = sorted(boundary_acres_by_name)
            best_matches = difflib.get_close_matches(raw_name, all_names, n=3, cutoff=0.0)
            request = confirm_mod.ConfirmationRequest(
                kind="naming_drift_alias",
                key=f"alias:{season}:{raw_name}",
                subject=(
                    f"Cost ledger name {raw_name!r} in season {season} has "
                    f"{len(acreage_candidates)} acreage candidates, not exactly 1"
                ),
                proposal={"canonical_boundary_name": best_matches[0] if best_matches else None},
                confidence="low",
                context={
                    "ledger_acres": raw_acres,
                    "acreage_candidates": acreage_candidates,
                    "string_candidates": best_matches,
                },
            )
            method = "ambiguous_match"

        response = confirm_fn(request)
        if not response.approved:
            raise confirm_mod.ConfirmationRejected(
                f"Alias for {raw_name!r} in season {season} was not confirmed", request=request
            )
        resolved.append(
            ResolvedAlias(season, raw_name, response.answer["canonical_boundary_name"], method)
        )

    return resolved


def resolve_all_aliases(
    con: duckdb.DuckDBPyConnection, seasons: list[int], confirm_fn: confirm_mod.ConfirmFn
) -> list[ResolvedAlias]:
    resolved: list[ResolvedAlias] = []
    for season in sorted(seasons):
        resolved.extend(resolve_season_aliases(con, season, confirm_fn))
    return resolved
