"""Which raw records sit behind an answer: the exact files, spreadsheet tabs
and rows a grower can open to check it by hand.

This only lists records; it computes nothing an answer depends on. The
caller says which kinds of record a lookup reads (see
farm_host.records.SOURCES_BY_TOOL) and for which field and seasons, and
gets back one entry per file (or spreadsheet tab), in a fixed order.
"""

from __future__ import annotations

from .pipeline import FarmSnapshot

# kind -> (table, field-name column or None, has a season column,
#          folder under the farm's data directory, plain-English label)
_KINDS: dict[str, tuple[str, str | None, bool, str, str]] = {
    "cost_ledger": ("cost_ledger_rows", "raw_field_name", True, "", "Cost ledger"),
    "unit_prices": ("unit_prices", None, True, "", "Unit prices"),
    "scale_tickets": ("scale_ticket_loads", "field_name", True, "scale_tickets", "Scale tickets"),
    "yield_monitor": ("yield_monitor_points", "field_name", True, "yield_monitor", "Yield monitor"),
    "boundaries": ("boundary_fields", "field_name", True, "boundaries", "Field boundaries"),
    "as_applied": ("as_applied_events", "field_name", True, "as_applied", "As-applied log"),
    "weather": ("weather_daily", None, True, "weather", "Weather"),
    "soil": ("soil_awc", "field_name", False, "weather", "Soil"),
}

KINDS = tuple(_KINDS)


class UnknownField(ValueError):
    pass


def _names_by_season(snap: FarmSnapshot, field_name: str) -> dict[int, set[str]]:
    """Every spelling of this field in each season: its boundary name plus
    any naming-drift alias the records used for it."""
    canonical_id = snap.canonical_id_for_name(field_name)
    if canonical_id is None:
        raise UnknownField(f"no field named {field_name!r} in these records")
    lineage = snap.identity.lineages[canonical_id]
    names = {season: {name} for season, name in lineage.display_name_by_season.items()}
    for (season, raw), canonical in snap.alias_map.items():
        if canonical == lineage.display_name_by_season.get(season):
            names.setdefault(season, set()).add(raw)
    return names


def _where(
    field_col: str | None,
    has_season: bool,
    names: dict[int, set[str]] | None,
    seasons: list[int] | None,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if has_season and seasons is not None:
        clauses.append(f"season IN ({', '.join('?' * len(seasons))})")
        params.extend(seasons)
    if field_col is not None and names is not None:
        if has_season:
            pairs = [(s, n) for s, ns in sorted(names.items()) for n in sorted(ns)]
            if not pairs:
                return "WHERE FALSE", []
            clauses.append(
                "(" + " OR ".join(f"(season = ? AND {field_col} = ?)" for _ in pairs) + ")"
            )
            for s, n in pairs:
                params.extend([s, n])
        else:
            all_names = sorted({n for ns in names.values() for n in ns})
            clauses.append(f"{field_col} IN ({', '.join('?' * len(all_names))})")
            params.extend(all_names)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _range(numbers: list[int], noun: str) -> str:
    numbers = sorted(set(numbers))
    if not numbers:
        return ""
    if len(numbers) == 1:
        return f"{noun} {numbers[0]}"
    if numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"{noun}s {numbers[0]}-{numbers[-1]}"
    if len(numbers) <= 6:
        return f"{noun}s " + ", ".join(str(n) for n in numbers)
    return f"{noun}s {numbers[0]}-{numbers[-1]} (not all in between)"


def _where_in_file(kind: str, snap: FarmSnapshot, source_file: str, where: str, params: list) -> str:
    con = snap.con
    table = _KINDS[kind][0]
    and_file = f"{where} AND source_file = ?" if where else "WHERE source_file = ?"
    p = [*params, source_file]
    if kind == "cost_ledger":
        rows = con.execute(f"SELECT row_index FROM {table} {and_file}", p).fetchall()
        # row_index counts from 0 at the sheet's first row, so +1 is the row
        # number Excel shows.
        return _range([r[0] + 1 for r in rows], "row")
    if kind == "scale_tickets":
        rows = con.execute(f"SELECT DISTINCT ticket_number FROM {table} {and_file}", p).fetchall()
        return _range([r[0] for r in rows], "ticket")
    if kind == "boundaries":
        rows = con.execute(f"SELECT DISTINCT field_name FROM {table} {and_file}", p).fetchall()
        names = sorted(r[0] for r in rows)
        if len(names) > 3:
            return f"{len(names)} field shapes"
        return "the " + ", ".join(names) + (" shape" if len(names) == 1 else " shapes")
    if kind == "as_applied":
        rows = con.execute(
            f"SELECT DISTINCT product FROM {table} {and_file} ORDER BY 1", p
        ).fetchall()
        return ", ".join(r[0] for r in rows)
    if kind == "unit_prices":
        rows = con.execute(f"SELECT DISTINCT season FROM {table} {and_file}", p).fetchall()
        return _range([r[0] for r in rows], "season")
    if kind == "soil":
        rows = con.execute(f"SELECT DISTINCT field_name FROM {table} {and_file}", p).fetchall()
        return "the " + ", ".join(sorted(r[0] for r in rows)) + " row"
    return ""


# kind -> (one, many)
_COUNT_NOUN = {
    "cost_ledger": ("row", "rows"),
    "unit_prices": ("row", "rows"),
    "scale_tickets": ("load", "loads"),
    "yield_monitor": ("point", "points"),
    "boundaries": ("field", "fields"),
    "as_applied": ("pass", "passes"),
    "weather": ("day", "days"),
    "soil": ("row", "rows"),
}


def _display_path(kind: str, source_file: str) -> tuple[str, str | None]:
    """(path relative to the farm folder, spreadsheet tab or None)."""
    if "::" in source_file:
        workbook, tab = source_file.split("::", 1)
        return workbook, tab
    folder = _KINDS[kind][3]
    return (f"{folder}/{source_file}" if folder else source_file), None


def records_behind(
    snap: FarmSnapshot,
    kinds: list[str],
    field_name: str | None = None,
    seasons: list[int] | None = None,
) -> list[dict]:
    """One entry per file or spreadsheet tab, in the order of `kinds`:
    {"kind", "label", "path", "tab", "rows", "which"}. `rows` counts the
    matching records in that file and `which` says which ones in words a
    grower can find (spreadsheet rows, ticket numbers, products).

    field_name=None means every field; seasons=None means every season.
    """
    unknown = [k for k in kinds if k not in _KINDS]
    if unknown:
        raise ValueError(f"unknown record kinds {unknown}; known: {list(_KINDS)}")
    names = _names_by_season(snap, field_name) if field_name else None

    out: list[dict] = []
    for kind in dict.fromkeys(kinds):
        table, field_col, has_season, _folder, label = _KINDS[kind]
        where, params = _where(field_col, has_season, names, seasons)
        counts = snap.con.execute(
            f"SELECT source_file, count(*) FROM {table} {where} GROUP BY 1 ORDER BY 1", params
        ).fetchall()
        for source_file, n in counts:
            path, tab = _display_path(kind, source_file)
            one, many = _COUNT_NOUN[kind]
            out.append(
                {
                    "kind": kind,
                    "label": label,
                    "path": path,
                    "tab": tab,
                    "rows": n,
                    "count_text": f"{n:,} {one if n == 1 else many}",
                    "which": _where_in_file(kind, snap, source_file, where, params),
                }
            )
    return out
