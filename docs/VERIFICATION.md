# Verification

How Precision Farm MCP is tested, what runs where, and what the tests
prove. For the overview, see the [README](../README.md).

## Running the tests

About 450 tests across five packages, including all 15
[evaluation questions](EVAL_QUESTIONS.md) at the tool level. Tests that
call the model need Ollama running with `gemma3:4b`; without it, only those
tests fail. Most tests read the example farms, so generate and confirm both
first (the [README](../README.md#quick-start) quick start).

| Package | Needs Ollama | Runs in CI |
|---|---|---|
| `generator` | No | Every PR |
| `core` | No | Every PR |
| `host` | Some (the `ollama` tests and the opt-in `eval_nl` suite) | Every PR without the model; all of it on demand |
| `model` | Some | On demand |
| `web` | No (the opt-in `ui` suite needs Playwright's Chromium) | Locally |
| `docs/test_architecture_doc.py` | No | Every PR |

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

Two workflows keep CI fast:

- **Pull requests** (`.github/workflows/tests.yml`) run one Ubuntu check:
  lint (`uvx ruff check .`, settings in `ruff.toml`), a check that every
  `uv.lock` is up to date, then `generator`, `core`, the architecture-doc
  test and every `host` test that doesn't call the model
  (`pytest -m "not eval_nl and not ollama"`), 4 tests at a time
  (`-n 4`, about 3 minutes). Docs-only changes skip CI. `-n 4` works
  locally too, for `core` and `host`.
  Windows isn't tested in CI: growers see the app on a Mac rather than
  installing it.
- **The real-model job** (`.github/workflows/real-model.yml`: all of `host`
  and `model` with Ollama on Ubuntu, 12 to 20 minutes) runs only when started
  by hand (Actions, real-model tests, Run workflow). There is no nightly run.
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
