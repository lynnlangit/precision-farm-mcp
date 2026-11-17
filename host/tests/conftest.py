"""Keep the host tests away from the user's own app state.

data/confirmed_mappings.json, data/confirmed_mappings_clean.json and
data/audit.jsonl are runtime state: farm-ingest writes them, and so does a
grower answering a confirmation in the web app or farm-cli. Tests that read
them see whatever the person last answered. For example, a person who
correctly confirms that 'Hom Corner' means Home Quarter (DEF-ALIASTIE) gets
10 seasons of Home Quarter on Farm 2 where the tests expect the 9 that the
auto-approved answer gives.

So before any test module is imported, this builds fresh auto-approved
confirmation stores for both example farms in a temporary folder and points
every test at them: FARMS, the CLIs' default paths, and every MCP server the
tests start (FARM_CONFIRM_STORE / FARM_AUDIT_LOG). The real files under data/
are never read or written. The generated data itself (data/synthetic*/) is
still read from the repo, since it is the same on every machine for a seed.
"""

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import io
import shutil
import tempfile
from pathlib import Path

from farm_core.audit import AuditLog
from farm_host import cli, farms, ingest_cli, mcp_client, metrics_cli, preflight_cli

_TMP = Path(tempfile.mkdtemp(prefix="farm-host-tests-"))
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)

TEST_AUDIT_LOG = _TMP / "audit.jsonl"

for _key, _farm in list(farms.FARMS.items()):
    _store = _TMP / _farm.confirm_store.name
    if (_farm.data_dir / "ground_truth.json").is_file():
        with contextlib.redirect_stdout(io.StringIO()):
            ingest_cli.run_ingest(
                _farm.data_dir,
                _store,
                AuditLog(_TMP / "ingest-audit.jsonl"),
                auto_approve_synthetic_only=True,
            )
    # Replaced in place, so `from farm_host.farms import FARMS` sees it.
    farms.FARMS[_key] = dataclasses.replace(_farm, confirm_store=_store)

TEST_CONFIRM_STORE = farms.FARMS["farm2"].confirm_store

for _module in (cli, ingest_cli, metrics_cli, preflight_cli):
    if hasattr(_module, "DEFAULT_CONFIRM_STORE"):
        _module.DEFAULT_CONFIRM_STORE = TEST_CONFIRM_STORE
    _module.DEFAULT_AUDIT_LOG = TEST_AUDIT_LOG

# Every server a test starts gets these unless the test passes its own.
mcp_client.DEFAULT_CHILD_ENV.update(
    FARM_CONFIRM_STORE=str(TEST_CONFIRM_STORE),
    FARM_AUDIT_LOG=str(TEST_AUDIT_LOG),
)
