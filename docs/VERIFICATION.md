# Verification

How Precision Farm MCP is tested, what runs where, and what the tests
prove. For the overview, see the [README](../README.md).

## Running the tests

About 490 tests across five packages, including all 15
[evaluation questions](EVAL_QUESTIONS.md) at the tool level. Tests that
call the model need Ollama running with `gemma3:4b`; without it, only those
tests fail. Most tests read the example farms, so generate and confirm both
first (the [README](../README.md#quick-start) quick start).

| Package | Tests | Needs Ollama | Runs in CI |
|---|---|---|---|
| `generator` | 19 | No | Every PR |
| `core` | 97 | No | Every PR |
| `host` | 230 (27 opt-in `eval_nl`) | The `ollama` and `eval_nl` tests | Every PR without the model; all of it on demand |
| `model` | 119 | Some | On demand |
| `web` | 70 (25 opt-in `ui`, needing Playwright's Chromium) | No | Locally |
| `docs/test_architecture_doc.py` | 2 | No | Every PR |

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

| When | What runs | Where |
|---|---|---|
| Every pull request (`.github/workflows/tests.yml`, about 3 minutes) | Lint (`uvx ruff check .`, settings in `ruff.toml`), every `uv.lock` up to date, `generator`, `core`, the architecture-doc test, and every `host` test that doesn't call the model (`-m "not eval_nl and not ollama"`). `core` and `host` run 4 at a time (`-n 4`, which works locally too). Docs-only changes skip CI | One Ubuntu runner. Windows isn't tested: growers see the app on a Mac |
| By hand only (`.github/workflows/real-model.yml`: Actions, real-model tests, Run workflow) | All of `host` and `model` with Ollama, 12 to 20 minutes. No nightly run | Ubuntu |
| Before a demo | The `host` and `model` suites, plus `eval_nl` | A Mac with Ollama, where Gemma is fast |
| Comparing models | `farm-evals --models gemma3:4b phi4-mini granite4:micro` ([MODELS.md](MODELS.md)) | A Mac with Ollama; never in CI |

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
  [9 checks](ARCHITECTURE.md#how-a-question-flows-in-the-web-app); it gets
  one try, so a failing sentence is withheld. Whether a given question's
  sentence fails depends on what the model writes on that machine: the
  East 80 example under "Bad field or bad year?" (eval 2) was withheld
  4 of 4 times on one Mac and 1 of 4 on another
  (`pytest -m eval_nl host/tests -k withheld`, xfail for that reason).
  `scripts/probe_narration.py` re-checks any question against the real
  model
- 📊 **Governance is measurable**: `farm-metrics` reports the human catch
  rate, tool grounding, narration faithfulness and sovereignty integrity
  straight from the audit log

## See also

[ARCHITECTURE.md](ARCHITECTURE.md) for the design; every other doc is listed in the [README](../README.md#start-here).
