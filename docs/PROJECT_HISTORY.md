# Precision Farm MCP — Project History

How the project got here, for anyone asking why something is built the
way it is. Release notes are in [CHANGELOG.md](../CHANGELOG.md); the
current design is in [ARCHITECTURE.md](ARCHITECTURE.md). The original
phase specs and planning notes are in git history (this file before
November 17, 2026).

## The original build

Before the lettered phases, the tool was built in numbered steps: field
identity from raw boundary files, ingestion and reconciliation of the raw
sources, the profitability engine and audit log, the MCP servers wrapping
`farm_core`, the bounded Gemma layer (parse and narrate only), and the
no-network checks. Each step was proven by the tests that still guard it.

## Phases 0, 1 and A–D

| Phase | What it did | What it found or fixed along the way |
|---|---|---|
| 0, audit | Reviewed the first build | The confirmation gate was inert (`auto_approve` default); the audit hash chain broke under concurrent writes; no provenance or prompt-injection defense |
| 1, confirmation made real | `farm-ingest`, `ConfirmationGate`, versioned `PersistedConfirm`, fail-closed `build_farm_snapshot`, `confirmation_required` refusals | `DEF-ALIASTIE` proves the gate changes an outcome: auto-approval gives a confidently wrong answer |
| A1, audit log | Cross-platform file lock and backward-seek read | Proven with a real multi-process test. `data/audit.jsonl` and `data/confirmed_mappings.json` became gitignored (earlier copies remain in git history) |
| A2, provenance | Every response reserves a `modeled` field | |
| A3, grounding | Grounding split into measured/derived and modeled rates | |
| A4, untrusted text | `MCPFleet.call()` returns `ToolResult(data, untrusted_paths)`; free text delimited for the prompt and redacted for grounding; payload capping | Numbers quoted inside injected text were grounding themselves. `provenance` timestamps were also being number-mined; now excluded. `DEF-INJECTION` proves narration is unaffected |
| B1, metrics | `farm-metrics`: human catch rate, tool grounding, narration faithfulness, sovereignty integrity | The `narration` audit event only logged the question, so two metrics had no data; enriched. Every rate is `null`, not `0`, with no denominator |
| B2, architecture doc | `docs/ARCHITECTURE.md` and `docs/test_architecture_doc.py` | An order-dependent bug in `test_no_network.py`'s fixture (a reused Ollama connection); fixed without weakening the check |
| C1, weather | AR(1) daily weather per season, soil AWC per field; yield became weather-driven | `CATASTROPHIC_YIELD_FACTOR` tightened 0.25 to 0.10 so ordinary weather doesn't trip the outlier rule |
| C2, regeneration | Qualitative fixtures pinned; `docs/EVAL_QUESTIONS.md` generated from `ground_truth.json`, never hand-edited | |
| C3, two shortfalls | `DEF-WEATHERSHORTFALL` (forced drought) and `DEF-MGMTSHORTFALL` (management) | |
| C4, attribution | `core/expectation.py`: `season_effect` and `residual`; `mcp-weather-history`; `modeled.attribution` on `bad_year`; `EXPLAIN_SHORTFALL`; `attribution_backtest` | A sentence citing one measured and one modeled number failed both grounding channels; fixed so only a number grounded in neither fails |
| D, zones | `core/zone_profitability.py` (2x2 grid), two `report-export` tools, `DEF-BADZONE` | As-applied data has no real spatial resolution, so zone cost is field-uniform and only yield is zone-resolved (a Diverged row in ARCHITECTURE.md) |

## Workshop preparation

General-purpose changes (no workshop- or org-specific content in this
repo) so installation can happen before a session, not during it:

- `ParseFailure.kind` tells a dead Ollama from an out-of-scope question.
- `farm-cli` and `farm-ingest` exit non-zero on any refusal.
- `farm-preflight` checks uv, Ollama, the model, the data and ingest, then
  runs a live query.
- `farm-cli --intent`: a model-free path, structured arguments in, JSON
  out, as a fallback if Ollama hiccups mid-demo.
- `farm-ingest --auto-approve-synthetic-only`, refused outside the example
  data.
- A deterministic "therefore" line after each answer.
- `docs/FARMER_GUIDE.md` leads with a no-git ZIP download.

## v0.1.0 onward (November 2026): eval fixes and the grower web app

One PR per step, merged in order. The eval fix plan was P0–P5.

| PR | Change |
|---|---|
| #2 (P1) | Fixed the deterministic answer text for evals 3, 4, 5 and 7 |
| #3 (P2) | Cost questions route correctly; numeric field names are refused |
| #4 (P0) | Generator rounds prices and $/ac first, so the answer key matches the raw files |
| #5 (P3) | Semantic narration checks: sign, zone premise, reconciliation, attribution |
| #6 (P3b) | Template-first narration: a verified sentence always leads |
| #7 (P3c) | Unsupported-cause check rejects invented causes |
| #8 (P4) | `farm-cli` and server startup cleaned up for live demos |
| #9 | CI: deterministic jobs on PRs, real-model suite nightly and on demand |
| #10 (P5) | Tests for all 11 eval questions, opt-in `eval_nl` runner, single version 0.1.0, tag `v0.1.0` |
| #11 | Grower web app (`farm-web`, Gradio), local only unless `--lan` |
| #12 | Unsupported-cause check matches word forms (planted, flooded) |
| #13 | README leads with the web app; `docs/VERIFICATION.md` added |
| #14 (v0.1.1) | Docs reviewed against the code; all packages, generator included, on one version |
| #15 | Follow-up questions in the web app ("Showing:" line, now "Talking about:"; "Ask next" buttons) |
| #16 | MCP servers kept running between questions (~4 s to ~0.2 s per lookup); tidier page |
| #17 | Farm 1 / Farm 2 picker (clean vs. messy records); Riverside renamed Sheyenne Bottom |
| #18 | All six MCP servers used: weather, soil and as-applied questions (evals 12-15), `units` check |
| #19 | Decluttered web app; the answer card shows a withheld AI sentence |
| #20 | Question-flow diagram added to ARCHITECTURE.md |
| #21 | One AI try by default, so the withheld-sentence demo (eval 2) works with real Gemma |
| #22 | Each question sent exactly once (Enter to send, locked while answering); browser tests |
| #23 | Second docs review; screenshots retaken on a Mac; three hard problems moved to ARCHITECTURE.md |
| #24 | Multi-turn follow-up pairs in EVAL_QUESTIONS.md; East 80 example moved third |
| #25 | Clearer web app: Clear renamed "↺ New subject" on the "Talking about:" line, slim banner, checks and numbers folded to one line each, bigger text |
| #26 | Docs brought up to date; README screenshots retaken with real Gemma |
| #27 | "Show the records" lists the files, tabs and rows behind each answer (`records_behind` tool); `docs/YOUR_RECORDS.md`; question-flow diagram renders on GitHub again |
| #28 | Records-list fields classified for the untrusted-text check |
| #29 | CI simplified: one Ubuntu PR check (generator, core, host without the model); real-model job manual only, no nightly; Windows dropped from CI |
| #30 | PR check runs core and host tests 4 at a time (pytest-xdist): about 7 min to about 3 |
| #31 (v0.2.0) | Every package on 0.2.0; release notes in [CHANGELOG.md](../CHANGELOG.md); tag `v0.2.0` |
| #32 | Host tests never read or write the app's own state under `data/` |
| #33 | README shortened (115 to 57 lines); new `docs/DEVELOPER.md` |
| #34 | Tidier home screen: example questions nested under one "Example questions (5 types)" row; farm description line removed |
| #35, #37–#39 | Repo tidy: docs de-duplicated; ruff and `uv lock --check` in the PR check; `farm-preflight` checks both farms; the six servers share `core/server_support.py` |
| #40 | README screenshot retaken after the home screen tidy |
| #43 | Brick Ellis with Lynn: `scripts/run_evals.py` (expected vs. actual answer per eval question); profit computed in exact Decimal so every platform gets the same cents; "last five years" always the latest five known seasons; parser refusal kinds |
| #44 | Brick Ellis with Lynn: a 9th check, `season_count`; eval 3's Therefore line no longer repeats the answer; eval 9 wording |
| #45 | Gold "What that means" line removed from the answer card (`farm-cli` keeps "Therefore:") |
| #46 | New README hero screenshot; "What you see in every answer" as a table |
| #47 | A few meaningful icons: answer labels, the two folded panels, and each example question type |

## Where to resume

Nothing is queued. Deferred work (live weather and a sync boundary, remote
sensing, a prescriptive crop model, absolute agronomy calibration) is in
the Deferred rows of [ARCHITECTURE.md's component table](ARCHITECTURE.md#component-status).
