"""farm-preflight: each check gets its own pass/fail path, tested with fakes
where a real dependency would be slow or non-deterministic (a missing uv, a
dead Ollama, an unpulled model), plus one live run against the real
synthetic data and a real Ollama -- the same "no mocking the thing that
actually proves readiness" convention as model/tests/test_model_bounded.py.
"""

from pathlib import Path

from farm_host.preflight_cli import (
    DEFAULT_TEST_QUESTION,
    check_confirmed_mappings,
    check_live_query,
    check_model_pulled,
    check_synthetic_data,
    check_uv,
    run_all,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "synthetic"
CONFIRM_STORE_PATH = REPO_ROOT / "data" / "confirmed_mappings.json"
AUDIT_LOG_PATH = REPO_ROOT / "data" / "audit.jsonl"


def test_check_uv_passes_when_on_path():
    assert check_uv().ok


def test_check_model_pulled_fails_when_ollama_unreachable():
    result = check_model_pulled(None)
    assert not result.ok
    assert "not reachable" in result.detail


def test_check_model_pulled_fails_when_model_missing():
    result = check_model_pulled(["some-other-model:latest"])
    assert not result.ok
    assert result.fix is not None
    assert "ollama pull gemma3:4b" in result.fix


def test_check_model_pulled_passes_when_present():
    assert check_model_pulled(["gemma3:4b", "mistral:7b"]).ok


def test_check_synthetic_data_fails_on_empty_dir(tmp_path):
    result = check_synthetic_data(tmp_path)
    assert not result.ok
    assert "farm_data_gen.cli" in result.fix


def test_check_synthetic_data_passes_against_real_data():
    assert check_synthetic_data(DATA_DIR).ok


def test_check_confirmed_mappings_fails_when_missing(tmp_path):
    result = check_confirmed_mappings(tmp_path / "no_such_file.json")
    assert not result.ok
    assert "farm-ingest" in result.fix


def test_check_confirmed_mappings_passes_against_real_store():
    assert check_confirmed_mappings(CONFIRM_STORE_PATH).ok


def test_live_query_check_succeeds_against_real_data_and_ollama():
    result = check_live_query(DATA_DIR, CONFIRM_STORE_PATH, AUDIT_LOG_PATH, DEFAULT_TEST_QUESTION)
    assert result.ok, result.detail


def test_run_all_reports_ready_against_real_setup():
    results = run_all(DATA_DIR, CONFIRM_STORE_PATH, AUDIT_LOG_PATH, DEFAULT_TEST_QUESTION)
    names = [r.name for r in results]
    assert names == [
        "uv installed",
        "Ollama running",
        "gemma3:4b pulled",
        "farm data generated",
        "farm-ingest has run",
        "end-to-end query",
    ]
    assert all(r.ok for r in results)


def test_run_all_skips_live_query_when_an_earlier_check_fails(tmp_path):
    results = run_all(tmp_path, CONFIRM_STORE_PATH, AUDIT_LOG_PATH, DEFAULT_TEST_QUESTION)
    assert [r.name for r in results][-1] != "end-to-end query"
