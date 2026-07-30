"""Phase A / A4 verification: every string-typed field across every server's
response models is classified as either deterministic (the host/tests rely
on its exact value) or untrusted free text (sanitized before reaching the
model) in farm_host.mcp_client's two sets. An unclassified string field
fails this test -- that's what catches the *next* free-text field the day
someone adds one, replacing "extend this set as new ones appear" with an
actual build failure instead of a comment nobody reads.

Introspects each server's own Pydantic response models directly (via a
`python -c "import ..."` subprocess in that server's own project/venv,
never `python -m` -- that would start the actual MCP server) rather than the
MCP-advertised output schema: every tool function is deliberately annotated
`-> dict` (see mcp_report_export.server's module docstring for why), so the
wire-level schema doesn't reflect the real Pydantic models at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from farm_host.mcp_client import DETERMINISTIC_STRING_FIELDS, UNTRUSTED_FREE_TEXT_FIELDS

_SERVERS_DIR = Path(__file__).resolve().parents[2] / "servers"

# server directory -> importable module
_SERVER_MODULES = {
    "mcp-report-export": "mcp_report_export.server",
    "mcp-field-registry": "mcp_field_registry.server",
    "mcp-yield-history": "mcp_yield_history.server",
    "mcp-as-applied": "mcp_as_applied.server",
    "mcp-cost-ledger": "mcp_cost_ledger.server",
}

_INTROSPECT_SNIPPET = """
import importlib, json
from pydantic import BaseModel
mod = importlib.import_module("{module}")
schemas = {{}}
for name in dir(mod):
    obj = getattr(mod, name)
    # __module__ check excludes imported models (e.g. mcp.types.ToolAnnotations)
    # -- only classes this server actually defines are its response models.
    if (
        isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj is not BaseModel
        and obj.__module__ == mod.__name__
    ):
        schemas[name] = obj.model_json_schema()
print(json.dumps(schemas))
"""


def _response_model_schemas(server_dir: str, module: str) -> dict[str, dict]:
    server_path = _SERVERS_DIR / server_dir
    proc = subprocess.run(
        ["uv", "run", "--project", str(server_path), "python", "-c", _INTROSPECT_SNIPPET.format(module=module)],
        capture_output=True,
        text=True,
        check=True,
        cwd=server_path,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _resolve(node: dict, defs: dict) -> dict:
    if isinstance(node, dict) and "$ref" in node:
        return defs.get(node["$ref"].rsplit("/", 1)[-1], {})
    return node


def _string_field_names(schema: dict) -> set[str]:
    """Every property name, anywhere in the schema (recursing through
    objects, arrays, and $ref/anyOf), whose resolved type includes "string".
    """
    defs = schema.get("$defs", {})
    names: set[str] = set()
    visited: set[int] = set()

    def walk(node: dict) -> None:
        node = _resolve(node, defs)
        if not isinstance(node, dict) or id(node) in visited:
            return
        visited.add(id(node))

        for prop_name, prop_schema in node.get("properties", {}).items():
            resolved = _resolve(prop_schema, defs)
            candidates = [resolved, *[_resolve(o, defs) for o in resolved.get("anyOf", [])]]
            if any(c.get("type") == "string" for c in candidates):
                names.add(prop_name)
            for candidate in candidates:
                walk(candidate)
                if candidate.get("type") == "array":
                    walk(candidate.get("items", {}))

    walk(schema)
    return names


def test_every_response_model_string_field_is_classified():
    known = DETERMINISTIC_STRING_FIELDS | UNTRUSTED_FREE_TEXT_FIELDS
    unclassified: dict[str, set[str]] = {}

    for server_dir, module in _SERVER_MODULES.items():
        schemas = _response_model_schemas(server_dir, module)
        for model_name, schema in schemas.items():
            missing = _string_field_names(schema) - known
            if missing:
                unclassified.setdefault(f"{server_dir}.{model_name}", set()).update(missing)

    assert not unclassified, (
        f"Unclassified string field(s) found -- add each to either "
        f"DETERMINISTIC_STRING_FIELDS or UNTRUSTED_FREE_TEXT_FIELDS in "
        f"farm_host/mcp_client.py: {unclassified}"
    )
