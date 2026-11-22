"""farm-evals: ask the eval questions (docs/EVAL_QUESTIONS.md) through the
real path with one or more Ollama models, grade every answer against the
answer key (farm_host.eval_key), and print a side-by-side table.

Developers only. The grower web app always uses gemma3:4b. From the repo root:

    uv run --project host farm-evals                          # gemma3:4b only
    uv run --project host farm-evals --models gemma3:4b phi4-mini
    uv run --project host farm-evals --models phi4-mini --ids 2 9 farm1-eval7

Pull each model first (`ollama pull phi4-mini`); a model that isn't pulled is
skipped and named in the report. Writes data/model_comparison.md (git-ignored)
unless --out says otherwise. Read-only: audit logs go to a temporary folder.
Exits 1 when any graded question failed. See docs/MODELS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from farm_core.audit import AuditLog

from .cli import answer_question
from .eval_key import EVALS, FARM1_EVALS, Eval, Grade, grade
from .farms import FARMS, REPO_ROOT
from .preflight_cli import REQUIRED_MODEL, check_ollama_running

DEFAULT_OUT = REPO_ROOT / "data" / "model_comparison.md"


@dataclasses.dataclass
class Run:
    model: str
    ev: Eval
    grade: Grade
    sentence: str  # "shown", "withheld" or "none": the one AI-written sentence
    seconds: float
    text: str


def _sentence(result) -> str:
    n = result.narration
    if n is None:
        return "none"
    if n.context:
        return "shown"
    return "withheld" if n.rejected_texts else "none"


async def _ask(model: str, ev: Eval, tmp: Path) -> Run:
    log = tmp / f"{model.replace(':', '_').replace('/', '_')}-{ev.id}.jsonl"
    env = {"FARM_AUDIT_LOG": str(log), **FARMS[ev.farm].server_env()}
    start = time.monotonic()
    try:
        result = await answer_question(ev.question, AuditLog(log), env_overrides=env, model=model)
    except Exception as e:  # noqa: BLE001 -- one broken question shouldn't lose the rest
        return Run(model, ev, Grade(route=[f"error: {type(e).__name__}: {e}"]), "none",
                   time.monotonic() - start, "")
    seconds = time.monotonic() - start
    events = AuditLog(log).entries()
    return Run(model, ev, grade(ev, result, events), _sentence(result), seconds, result.text)


def _cell(run: Run) -> str:
    g = run.grade
    if g.passed:
        return "pass"
    stage = "route" if g.route else "args" if g.args else "answer"
    return f"**FAIL** ({stage})"


def report(models: list[str], runs: list[Run], skipped: dict[str, str]) -> str:
    evs: list[Eval] = []
    for r in runs:
        if r.ev not in evs:
            evs.append(r.ev)
    by = {(r.model, r.ev.id): r for r in runs}
    ran = [m for m in models if m not in skipped]

    out = [
        "# Model comparison -- eval questions",
        "",
        f"Run {datetime.now():%Y-%m-%d %H:%M}, {len(evs)} question(s) per model, graded "
        "against the answer key in `host/src/farm_host/eval_key.py` "
        "(from `docs/EVAL_QUESTIONS.md`).",
        "",
        "## Summary",
        "",
        "| Model | Passed | Wrong route | Wrong field/season | Wrong answer "
        "| AI sentence shown | AI sentence withheld | Avg seconds |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m in ran:
        rs = [r for r in runs if r.model == m]
        n = len(rs)
        out.append(
            f"| `{m}` | {sum(r.grade.passed for r in rs)} of {n} "
            f"| {sum(bool(r.grade.route) for r in rs)} "
            f"| {sum(bool(r.grade.args) and not r.grade.route for r in rs)} "
            f"| {sum(bool(r.grade.answer) and not r.grade.route for r in rs)} "
            f"| {sum(r.sentence == 'shown' for r in rs)} "
            f"| {sum(r.sentence == 'withheld' for r in rs)} "
            f"| {sum(r.seconds for r in rs) / max(n, 1):.1f} |"
        )
    for m, why in skipped.items():
        out.append(f"| `{m}` | skipped: {why} | | | | | | |")

    out += [
        "",
        "## By question",
        "",
        "| Eval | Question | " + " | ".join(f"`{m}`" for m in ran) + " |",
        "|---|---|" + "---|" * len(ran),
    ]
    for ev in evs:
        cells = [_cell(by[(m, ev.id)]) for m in ran]
        out.append(f"| {ev.id} | {ev.question} | " + " | ".join(cells) + " |")

    failed = [r for r in runs if not r.grade.passed]
    out += ["", "## What failed", ""]
    if not failed:
        out.append("Nothing: every question matched the answer key.")
    for r in failed:
        out.append(f"- `{r.model}` {r.ev.id}: " + "; ".join(r.grade.problems()))
    out.append("")
    return "\n".join(out)


async def run(models: list[str], evs: list[Eval]) -> tuple[list[Run], dict[str, str]]:
    running, pulled = check_ollama_running()
    skipped: dict[str, str] = {}
    if not running.ok:
        return [], {m: running.detail for m in models}
    for m in models:
        if m not in (pulled or []):
            skipped[m] = f"not pulled (`ollama pull {m}`)"
    runs: list[Run] = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for m in models:
            if m in skipped:
                continue
            for ev in evs:
                print(f"[{m}] {ev.id}: {ev.question}", file=sys.stderr, flush=True)
                r = await _ask(m, ev, tmp)
                print(f"    {_cell(r)}  ({r.seconds:.1f}s)", file=sys.stderr, flush=True)
                runs.append(r)
    return runs, skipped


def _with_tag(model: str, pulled: list[str] | None) -> str:
    """Ollama lists `phi4-mini` as `phi4-mini:latest`."""
    if ":" in model or pulled is None:
        return model
    return f"{model}:latest" if f"{model}:latest" in pulled else model


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="farm-evals", description=__doc__.split("\n\n")[0])
    p.add_argument("--models", nargs="+", default=[REQUIRED_MODEL],
                   help=f"Ollama models to compare (default: {REQUIRED_MODEL})")
    p.add_argument("--ids", nargs="+",
                   help="only these evals, e.g. 2 9 farm1-eval7 (default: all 15 + 4 Farm 1)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)

    evs = EVALS + FARM1_EVALS
    if args.ids:
        wanted = {i if i.startswith(("eval", "farm1-")) else f"eval{i}" for i in args.ids}
        unknown = wanted - {e.id for e in evs}
        if unknown:
            p.error(f"no such eval(s): {', '.join(sorted(unknown))}")
        evs = [e for e in evs if e.id in wanted]

    _, pulled = check_ollama_running()
    models = list(dict.fromkeys(_with_tag(m, pulled) for m in args.models))
    runs, skipped = asyncio.run(run(models, evs))
    text = report(models, runs, skipped)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    summary = text.split("## By question")[0].split("## Summary")[1].strip()
    print(summary)
    print(f"\nWrote {args.out}", file=sys.stderr)
    return 0 if runs and all(r.grade.passed for r in runs) and not skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
