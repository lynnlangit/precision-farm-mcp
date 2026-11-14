# Verification

How Precision Farm MCP is tested, what runs where, and what the tests
prove. For the overview, see the [README](../README.md).

## Running the tests

About 400 tests across five packages, including all 15
[evaluation questions](EVAL_QUESTIONS.md) at the tool level. Tests that
call the model need Ollama running with `gemma3:4b`; without it, only those
tests fail.

| Package | Tests | Needs Ollama | Runs in CI |
|---|---|---|---|
| `generator` | 19 | No | Every PR (Ubuntu and Windows) |
| `core` | 84 | No | Every PR (Ubuntu and Windows) |
| `host` | 150, of which 27 are the opt-in `eval_nl` suite | Some | Nightly and on demand (Ubuntu) |
| `model` | 96 | Some | Nightly and on demand (Ubuntu) |
| `web` | 57, of which 25 are the opt-in `ui` browser suite | No | Locally |
| `docs/test_architecture_doc.py` | 1 | No | Locally |

```bash
for pkg in generator core host model web; do (cd $pkg && uv run pytest -q); done
uv run --project core pytest -q docs/test_architecture_doc.py
```

Two opt-in suites are skipped by default:

```bash
# The 15 eval questions end to end in plain English, plus the follow-up and
# withheld-sentence runs: Gemma parses, the host routes, the answer is checked
uv run --project host pytest -m eval_nl host/tests

# The web app's question box and buttons driven in a real browser
# (once: uv run --project web playwright install chromium)
uv run --project web pytest -m ui web/tests
```

## CI and demos

`.github/workflows/tests.yml` keeps CI fast:

- **Pull requests** run only `generator` and `core` (no Ollama), on Ubuntu
  and Windows. Docs-only changes skip CI.
- **The real-model job** (`host` and `model` with Ollama on Ubuntu, about
  12 minutes) runs nightly and on demand (Actions, tests, Run workflow).
- **Before a demo**, run the `host` and `model` suites, and the `eval_nl`
  suite, on a Mac with Ollama, where Gemma is fast.

## What the tests prove

- 💰 **Profit matches ground truth** for every field and season without a
  deliberate defect
- 🔍 **Every injected defect is caught by its ID**, including
  `DEF-ALIASTIE`, which proves auto-approval gives a confidently *wrong*
  answer where human confirmation gives the right one
- 🌐 **Zero non-loopback network calls** (`test_no_network.py`)
- 🔗 **The audit log stays tamper-evident** under real concurrent writes
  from the host and two live server processes (`test_audit_multiprocess.py`)
- 🛡️ **Prompt injection has no effect**: `DEF-INJECTION` proves the
  narration is unaffected, not just non-crashing (`test_injection_defect.py`)
- 🚪 **The model-free path really is model-free**: `farm-cli --intent ...`
  answers with zero `ollama.chat` calls
  (`test_structured_path_never_calls_ollama`)
- ✅ **Answers lead with verified text, and the AI's sentence is checked.**
  The model's one added sentence is shown only if it passes all
  [8 checks](ARCHITECTURE.md#how-a-question-flows-in-the-web-app); it gets
  one try, so a failing sentence is withheld. The "When the AI is stopped"
  example (eval 2) is one `gemma3:4b` has failed every time we've measured
  (`pytest -m eval_nl host/tests -k withheld`). Sampling uses a fixed seed,
  so a given machine mostly gives the same sentence each run;
  `scripts/probe_narration.py` re-checks any question against the real
  model
- 📊 **Governance is measurable**: `farm-metrics` reports the human catch
  rate, tool grounding, narration faithfulness and sovereignty integrity
  straight from the audit log

## See also

- [ARCHITECTURE.md](ARCHITECTURE.md): the technical design
- [EVAL_QUESTIONS.md](EVAL_QUESTIONS.md): the 15 evaluation questions and their verifiable answers
