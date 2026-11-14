"""Ask questions through the real path (Gemma parses, a tool answers, Gemma
adds a checked sentence) and print what the AI wrote and what the checks did.
Use it to find or re-check the web app's "When the AI is stopped" example.
Needs Ollama with gemma3:4b and both farms' data. From the repo root:

    uv run --project host python scripts/probe_narration.py
    uv run --project host python scripts/probe_narration.py "Was East 80 a bad field or just a bad year?"

Read-only: each question's audit log goes to a temporary folder.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from farm_core.audit import AuditLog
from farm_host.cli import answer_question
from farm_host.farms import FARMS

DEFAULT_QUESTIONS = ["Was East 80 a bad field or just a bad year?"]


async def main(questions: list[str], runs: int = 2) -> int:
    withheld_everywhere = []
    for q in questions:
        tags = []
        for farm in FARMS:
            for run in range(1, runs + 1):
                d = Path(tempfile.mkdtemp())
                env = {"FARM_AUDIT_LOG": str(d / "a.jsonl"), **FARMS[farm].server_env()}
                r = await answer_question(q, AuditLog(d / "a.jsonl"), env_overrides=env)
                n = r.narration
                if n is None:
                    tag = f"refused ({r.refusal_kind})"
                elif n.context is None and n.rejected_texts:
                    tag = "WITHHELD"
                elif n.rejected_texts:
                    tag = "blocked, then shown"
                elif n.context:
                    tag = "shown"
                else:
                    tag = "nothing to add"
                tags.append(tag)
                print(f"{farm} run {run}: {tag} | {q}")
                if n is not None:
                    for text, failed in zip(n.rejected_texts, n.failed_checks):
                        print(f"   blocked ({', '.join(failed)}): {text}")
                    if n.context:
                        print(f"   shown: {n.context}")
        if all(t == "WITHHELD" for t in tags):
            withheld_everywhere.append(q)
    print("\nWithheld on every farm and run:")
    for q in withheld_everywhere:
        print(f"  {q}")
    return 0 if withheld_everywhere else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:] or DEFAULT_QUESTIONS)))
