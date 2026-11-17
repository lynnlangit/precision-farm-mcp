"""The host tests never read or write the person's own app state under data/
(see conftest.py): confirmations they answered, or their audit log."""

from farm_host import ingest_cli, mcp_client
from farm_host.farms import FARMS, REPO_ROOT

REAL_STATE = REPO_ROOT / "data"


def test_farms_use_throwaway_confirmation_stores():
    for farm in FARMS.values():
        assert not farm.confirm_store.resolve().is_relative_to(REAL_STATE.resolve())


def test_servers_and_clis_default_to_throwaway_state():
    for key in ("FARM_CONFIRM_STORE", "FARM_AUDIT_LOG"):
        assert not mcp_client.DEFAULT_CHILD_ENV[key].startswith(str(REAL_STATE))
    for path in (ingest_cli.DEFAULT_CONFIRM_STORE, ingest_cli.DEFAULT_AUDIT_LOG):
        assert not path.resolve().is_relative_to(REAL_STATE.resolve())
