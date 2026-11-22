"""Ask every question in docs/EVAL_QUESTIONS.md through the real path (Gemma
parses, the host routes to an MCP tool, Gemma narrates) and write a Markdown
report with each question's expected answer next to what the app actually
said, plus the tool and arguments it routed to.

The follow-up pairs (F1-F6) are asked the way the web app asks them: the
first question, then the follow-up with the first answer's context.

Needs Ollama with gemma3:4b. From the repo root:

    uv run --project host python scripts/run_evals.py              # all, Farm 2
    uv run --project host python scripts/run_evals.py 1 7 F2       # just these
    uv run --project host python scripts/run_evals.py --farm farm1 # clean records
    uv run --project host python scripts/run_evals.py --model phi4-mini

For a graded pass/fail table across several models, use farm-evals instead
(docs/MODELS.md).

Writes data/eval_results.md (git-ignored) unless --out says otherwise.
Read-only: audit logs go to a temporary folder, not data/audit.jsonl.

This is for eyeballing answers. The pass/fail version of the same questions
is `uv run --project host pytest -m eval_nl host/tests`.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from farm_core.audit import AuditLog
from farm_host.cli import AnswerResult, answer_question
from farm_host.farms import FARMS, REPO_ROOT
from farm_host.followups import next_context

EVAL_DOC = REPO_ROOT / "docs" / "EVAL_QUESTIONS.md"
DEFAULT_OUT = REPO_ROOT / "data" / "eval_results.md"

_HEADING = re.compile(r"^### (F?\d+)\. (.+)$")


@dataclasses.dataclass
class EvalCase:
    id: str  # "7" or "F2"
    title: str
    question: str  # for a follow-up, the follow-up itself
    expected: str  # the section's Tool / Verifiable answer lines, verbatim
    first: str | None = None  # the question asked before a follow-up


def _line_value(lines: list[str], label: str) -> str | None:
    prefix = f"**{label}:**"
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def parse_eval_doc(text: str) -> list[EvalCase]:
    cases: list[EvalCase] = []
    sections: list[tuple[str, str, list[str]]] = []
    body: list[str] | None = None
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            body = []
            sections.append((m.group(1), m.group(2), body))
        elif line.startswith(("---", "## ")):
            body = None  # a separator or summary heading ends the section
        elif body is not None:
            body.append(line)

    for case_id, title, body in sections:
        expected = "\n".join(
            line for line in body if line.startswith(("**Tool:**", "**Verifiable answer:**"))
        )
        if case_id.startswith("F"):
            first = _line_value(body, "First")
            then = _line_value(body, "Then")
            if not (first and then):
                continue
            first = re.sub(r"\s*\(question \d+\)\s*$", "", first)
            cases.append(EvalCase(case_id, title, then, expected, first=first))
        else:
            q = _line_value(body, "Q")
            if q:
                cases.append(EvalCase(case_id, title, q, expected))
    return cases


async def _ask(
    question: str, farm_env: dict[str, str], tmp: Path, context=None, model: str | None = None
) -> AnswerResult:
    log = tmp / f"audit-{time.monotonic_ns()}.jsonl"
    env = {"FARM_AUDIT_LOG": str(log), **farm_env}
    return await answer_question(
        question, AuditLog(log), env_overrides=env, context=context, model=model
    )


def _routing(r: AnswerResult) -> str:
    if r.tool is None:
        return f"no tool call (refusal: `{r.refusal_kind}`)"
    args = ", ".join(f"{k}={v!r}" for k, v in (r.tool_args or {}).items())
    status = "ok" if r.ok else f"refused: `{r.refusal_kind}`"
    return f"`{r.server}.{r.tool}({args})` -- {status}"


def _fence(text: str) -> str:
    return f"```text\n{text.rstrip()}\n```"


async def run(cases: list[EvalCase], farm_key: str, model: str | None = None) -> str:
    farm_env = FARMS[farm_key].server_env()
    out = [
        f"# Eval results -- {FARMS[farm_key].label}, model `{model or 'gemma3:4b'}`",
        "",
        f"Run {datetime.now():%Y-%m-%d %H:%M}, {len(cases)} question(s), "
        f"from `{EVAL_DOC.relative_to(REPO_ROOT)}`. "
        "Each section: what the eval doc expects, the tool the app actually called, "
        "and the app's full answer (what `farm-cli` prints).",
        "",
    ]
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for case in cases:
            print(f"[{case.id}] {case.question}", file=sys.stderr, flush=True)
            start = time.monotonic()
            out += [f"## {case.id}. {case.title}", ""]
            try:
                context = None
                if case.first:
                    first = await _ask(case.first, farm_env, tmp, model=model)
                    out += [
                        f"**First:** {case.first}",
                        f"**Routed to:** {_routing(first)}",
                        "",
                        _fence(first.text),
                        "",
                    ]
                    context = next_context(first, None)
                    out.append(f"**Then:** {case.question}")
                else:
                    out.append(f"**Q:** {case.question}")
                result = await _ask(case.question, farm_env, tmp, context=context, model=model)
                out += [
                    "",
                    "**Expected (from the eval doc):**",
                    "",
                    case.expected,
                    "",
                    f"**Routed to:** {_routing(result)}",
                    "",
                    "**Actual answer:**",
                    "",
                    _fence(result.text),
                ]
            except Exception as e:  # keep going: one broken question shouldn't lose the rest
                out += ["", f"**Error:** `{type(e).__name__}: {e}`"]
            out += ["", f"_{time.monotonic() - start:.1f}s_", "", "---", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("ids", nargs="*", help="eval ids to run, e.g. 1 7 F2 (default: all)")
    p.add_argument("--farm", choices=sorted(FARMS), default="farm2")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--model", help="Ollama model to use instead of gemma3:4b, e.g. phi4-mini")
    args = p.parse_args(argv)

    cases = parse_eval_doc(EVAL_DOC.read_text())
    if args.ids:
        wanted = {i.upper() for i in args.ids}
        unknown = wanted - {c.id for c in cases}
        if unknown:
            p.error(f"no such eval(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in wanted]

    report = asyncio.run(run(cases, args.farm, args.model))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(f"Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
