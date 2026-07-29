"""Deterministic file writers. Given identical in-memory content, every writer
here must produce byte-identical output across runs -- that's the whole
determinism guarantee, and it lives here rather than being scattered through
every format-specific module.
"""

from __future__ import annotations

import datetime
import json
import re
import zipfile
from pathlib import Path

import openpyxl

_FIXED_TIMESTAMP = datetime.datetime(2024, 1, 1, 0, 0, 0)
_FIXED_TIMESTAMP_ISO = _FIXED_TIMESTAMP.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
_MODIFIED_XML_RE = re.compile(
    rb'(<dcterms:modified xsi:type="dcterms:W3CDTF">)[^<]*(</dcterms:modified>)'
)


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, sort_keys=True, indent=2, separators=(",", ": "))
    path.write_text(text + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_workbook(path: Path, wb: openpyxl.Workbook) -> None:
    """Pin openpyxl's workbook metadata before saving -- it defaults created/
    modified to datetime.now() and creator to the OS username, either of which
    would make two runs with the same seed produce different XLSX bytes.

    openpyxl's save_workbook() unconditionally overwrites properties.modified
    with datetime.now() immediately before serializing (see
    openpyxl/writer/excel.py), ignoring whatever was set beforehand -- and
    every zip member it writes gets the real wall-clock time as its own
    per-entry date_time too. Both are patched as a post-processing pass on
    the saved zip; pinning properties.modified pre-save isn't enough on its
    own.
    """
    wb.properties.creator = "Precision Farm MCP synthetic generator"
    wb.properties.lastModifiedBy = "Precision Farm MCP synthetic generator"
    wb.properties.created = _FIXED_TIMESTAMP
    wb.properties.modified = _FIXED_TIMESTAMP
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    _pin_core_xml_modified(path)


_FIXED_ZIP_DATE_TIME = (2024, 1, 1, 0, 0, 0)


def _pin_core_xml_modified(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as zin:
        infos = zin.infolist()
        contents = {info.filename: zin.read(info.filename) for info in infos}

    core_xml = contents["docProps/core.xml"]
    contents["docProps/core.xml"] = _MODIFIED_XML_RE.sub(
        lambda m: m.group(1) + _FIXED_TIMESTAMP_ISO + m.group(2), core_xml
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            info.date_time = _FIXED_ZIP_DATE_TIME
            zout.writestr(info, contents[info.filename])
