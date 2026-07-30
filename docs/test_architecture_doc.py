"""Phase B / B2 verification: the server list in the architecture diagram
can't go stale without a test failing. Standalone -- no farm_core/farm_host
import, no project venv needed, so it runs even if nobody happens to be
inside one of the four packages' `uv` environments:

    pytest docs/test_architecture_doc.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE_DOC = REPO_ROOT / "docs" / "ARCHITECTURE.md"
SERVERS_DIR = REPO_ROOT / "servers"


def _documented_server_names() -> set[str]:
    doc_text = ARCHITECTURE_DOC.read_text(encoding="utf-8")

    fence_match = re.search(r"```mermaid\n(.*?)\n```", doc_text, re.DOTALL)
    assert fence_match, f"no mermaid fence found in {ARCHITECTURE_DOC}"

    subgraph_match = re.search(
        r"subgraph Servers\[.*?\]\n(.*?)\n\s*end\b", fence_match.group(1), re.DOTALL
    )
    assert subgraph_match, "no 'subgraph Servers[...]' block found in the diagram"

    names = set(re.findall(r'\["([\w-]+)"\]', subgraph_match.group(1)))
    assert names, "no server names found inside the Servers subgraph"
    return names


def _actual_server_names() -> set[str]:
    names = {p.name.removeprefix("mcp-") for p in SERVERS_DIR.iterdir() if p.is_dir()}
    assert names, f"no server directories found under {SERVERS_DIR}"
    return names


def test_architecture_doc_server_list_matches_servers_directory():
    documented = _documented_server_names()
    actual = _actual_server_names()
    assert documented == actual, (
        f"docs/ARCHITECTURE.md's diagram lists {documented}, but servers/ "
        f"actually has {actual} -- update the diagram (or the servers/ "
        f"directory) to match."
    )
