# Verification

How Precision Farm MCP is tested, and what the tests prove. For the
overview and quick start, see the [README](../README.md).

## Running the tests

About 300 tests across the five packages, including all 11 evaluation
questions from [EVAL_QUESTIONS.md](EVAL_QUESTIONS.md) at the tool level.
The host and model suites need Ollama running with `gemma3:4b`; without it,
only the tests that call the model fail.

| Package | Tests | Needs Ollama | Runs in CI |
|---|---|---|---|
| `generator` | 16 | No | Every PR (Ubuntu and Windows) |
| `core` | 74 | No | Every PR (Ubuntu and Windows) |
| `host` | 122 (11 are the opt-in `eval_nl` suite) | Some | Nightly and on demand |
| `model` | 74 | Some | Nightly and on demand |
| `web` | 13 | No | Locally |
| `docs/test_architecture_doc.py` | 1 | No | Locally |

```bash
for pkg in generator core host model web; do (cd $pkg && uv run pytest -q); done
uv run --project core pytest -q docs/test_architecture_doc.py
```

Before a demo, run the `host` and `model` suites on a machine with Ollama,
where Gemma is fast.

The same 11 questions also run end to end in plain English — Gemma parses
each one, the host routes it, and the answer's figures, summary line, or
refusal are checked. This suite is slow and opt-in:

```bash
uv run --project host pytest -m eval_nl host/tests
```

## What the tests prove

- 💰 **Profit matches ground truth** for every field/season without a
  deliberate defect
- 🔍 **Every injected defect is caught by its ID** — including
  `DEF-ALIASTIE`, proving auto-approval gives a confidently *wrong* answer
  where confirmation gives the right one
- 🌐 **Zero non-loopback network calls** (`test_no_network.py`)
- 🔗 **Audit log stays tamper-evident** under real concurrent writes from
  the host process and two live server subprocesses
  (`test_audit_multiprocess.py`)
- 🛡️ **Prompt injection has no effect** — `DEF-INJECTION` proves the
  narration is unaffected, not just non-crashing (`test_injection_defect.py`)
- 🚪 **The model-free query path really is model-free** —
  `farm-cli --intent ...` reaches an answer with zero `ollama.chat` calls,
  verified directly (`test_structured_path_never_calls_ollama`)
- ✅ **Answers lead with verified text** — every answer opens with a
  deterministic template sentence built from the tool result. The model may
  add one sentence of context, shown only if every number traces to the
  payload, no verdict is contradicted, and it passes five meaning checks
  (sign, zone premise, reconciliation, attribution, unsupported cause);
  otherwise it is dropped after one retry. The grower web app shows these
  checks next to every answer, including any attempt that was blocked
- 📊 **Governance is measurable, not just asserted** — `farm-metrics`
  reports HITL catch rate, tool grounding, narration faithfulness, and
  sovereignty integrity straight from the audit log

## See also

- [ARCHITECTURE.md](ARCHITECTURE.md) — the full technical design
- [EVAL_QUESTIONS.md](EVAL_QUESTIONS.md) — the eleven evaluation questions and their verifiable answers
