"""One-shot readiness check for Precision Farm MCP, meant to be run once
before relying on farm-cli. Five separately confusing failures (uv missing,
Ollama not running, model not pulled, data not generated, ingest not run)
otherwise all surface as the same opaque error from farm-cli itself -- this
gives each one its own line and its own fix command.

    uv run --project host farm-preflight
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

import ollama

from farm_core.audit import AuditLog

from .cli import answer_question

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "synthetic"
DEFAULT_CONFIRM_STORE = REPO_ROOT / "data" / "confirmed_mappings.json"
DEFAULT_AUDIT_LOG = REPO_ROOT / "data" / "audit.jsonl"
REQUIRED_MODEL = "gemma3:4b"
DEFAULT_TEST_QUESTION = "was the north eighty a bad field or a bad year"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


def check_uv() -> CheckResult:
    if shutil.which("uv") is None:
        return CheckResult(
            "uv installed",
            False,
            "not found on PATH",
            "install from https://astral.sh/uv (see docs/FARMER_GUIDE.md)",
        )
    return CheckResult("uv installed", True, "found on PATH")


def check_ollama_running() -> tuple[CheckResult, list[str] | None]:
    """Returns the check plus the list of pulled model names, if reachable
    (so check_model_pulled below doesn't have to make a second round trip).
    """
    try:
        models = ollama.Client().list()
    except Exception as e:  # noqa: BLE001 -- any transport failure means "not running"
        return (
            CheckResult(
                "Ollama running",
                False,
                f"not reachable ({e})",
                "start Ollama -- it usually runs in the background after install "
                "(open the Ollama app on macOS/Windows, or run `ollama serve` on Linux)",
            ),
            None,
        )
    return CheckResult("Ollama running", True, "reachable"), [m.model for m in models.models]


def check_model_pulled(pulled_models: list[str] | None) -> CheckResult:
    if pulled_models is None:
        return CheckResult(
            f"{REQUIRED_MODEL} pulled",
            False,
            "could not check -- Ollama is not reachable",
            None,
        )
    if REQUIRED_MODEL not in pulled_models:
        return CheckResult(
            f"{REQUIRED_MODEL} pulled",
            False,
            "not in `ollama list`",
            f"run `ollama pull {REQUIRED_MODEL}` (about 3.3 GB, one time)",
        )
    return CheckResult(f"{REQUIRED_MODEL} pulled", True, "present")


def check_synthetic_data(data_dir: Path) -> CheckResult:
    boundaries_dir = data_dir / "boundaries"
    if not boundaries_dir.is_dir() or not any(boundaries_dir.glob("*.geojson")):
        return CheckResult(
            "farm data generated",
            False,
            f"no boundary files under {boundaries_dir}",
            "run `uv run --project generator python -m farm_data_gen.cli "
            "--seed 42 --out data/synthetic`",
        )
    return CheckResult("farm data generated", True, f"found under {data_dir}")


def check_confirmed_mappings(confirm_store: Path) -> CheckResult:
    if not confirm_store.is_file():
        return CheckResult(
            "farm-ingest has run",
            False,
            f"{confirm_store} does not exist yet",
            "run `uv run --project host farm-ingest`",
        )
    return CheckResult("farm-ingest has run", True, f"found {confirm_store}")


def check_live_query(
    data_dir: Path,
    confirm_store: Path,
    audit_log_path: Path,
    question: str,
) -> CheckResult:
    audit_log = AuditLog(audit_log_path)
    try:
        result = asyncio.run(answer_question(question, audit_log))
    except Exception as e:  # noqa: BLE001 -- surfaced as a failed check, not a crash
        return CheckResult(
            "end-to-end query",
            False,
            f"raised an exception: {e}",
            "re-run the checks above one at a time; if they all pass, "
            "this may be a data/question mismatch -- try `--question` with "
            "something that matches your own data",
        )
    if not result.ok:
        return CheckResult(
            "end-to-end query",
            False,
            f'"{question}" was refused: {result.text}',
            "if this is the example question, something above this check is "
            "still not quite ready; if you changed --question, check it matches "
            "your own data's field names and seasons",
        )
    return CheckResult("end-to-end query", True, f'"{question}" -> "{result.text[:80]}..."')


def run_all(
    data_dir: Path,
    confirm_store: Path,
    audit_log_path: Path,
    question: str,
) -> list[CheckResult]:
    results = [check_uv()]

    ollama_check, pulled_models = check_ollama_running()
    results.append(ollama_check)
    results.append(check_model_pulled(pulled_models))
    results.append(check_synthetic_data(data_dir))
    results.append(check_confirmed_mappings(confirm_store))

    # Only worth attempting a real query if everything it depends on passed --
    # otherwise it just repeats one of the failures above with a stack trace.
    if all(r.ok for r in results):
        results.append(check_live_query(data_dir, confirm_store, audit_log_path, question))

    return results


def _print_results(results: list[CheckResult]) -> None:
    for r in results:
        mark = "OK  " if r.ok else "FAIL"
        print(f"[{mark}] {r.name}: {r.detail}")
        if not r.ok and r.fix:
            print(f"       fix: {r.fix}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="farm-preflight",
        description="Check that everything farm-cli needs is installed, running, "
        "and confirmed -- before relying on it.",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--confirm-store", type=Path, default=DEFAULT_CONFIRM_STORE)
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_LOG)
    parser.add_argument(
        "--question",
        default=DEFAULT_TEST_QUESTION,
        help="Question to use for the final end-to-end check "
        "(default assumes the example synthetic data is in place)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results = run_all(args.data_dir, args.confirm_store, args.audit_log, args.question)
    _print_results(results)
    all_ok = all(r.ok for r in results)
    print()
    print("Ready to use farm-cli." if all_ok else "Not ready yet -- follow the fix(es) above.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
