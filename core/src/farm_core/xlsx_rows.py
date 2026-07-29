"""Shared row-finding helpers for the messy cost-ledger workbook, used by both
the Phase 1 field-name-only reader and the Phase 2 full-column reader so the
messy-parsing logic (merged header, totals row, blank rows) lives in one place.
"""

from __future__ import annotations

from collections.abc import Iterator


def find_header_row(rows: list[tuple], header_cell: str = "Field") -> int:
    """Return the 0-based index of the real column-header row: the LAST in a
    run of consecutive rows whose first cell equals header_cell. A
    merged-header season has a spanner row above the real header that also
    starts with the same text -- the first match is the wrong one.
    """
    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0] == header_cell:
            header_idx = i
        elif header_idx is not None:
            break
    if header_idx is None:
        raise ValueError(f"No header row found (no row with {header_cell!r} in column A)")
    return header_idx


def iter_data_rows(rows: list[tuple], header_idx: int) -> Iterator[tuple[int, tuple]]:
    """Yield (row_index, row) for every real data row after the header,
    skipping blank rows and a totals row (column A == 'TOTAL', case-insensitive).
    """
    for row_index, row in enumerate(rows[header_idx + 1 :], start=header_idx + 1):
        if row is None or all(cell is None for cell in row):
            continue  # blank row
        first_cell = row[0]
        if first_cell is None:
            continue
        if str(first_cell).strip().upper() == "TOTAL":
            continue  # totals row inside the data range
        yield row_index, row
