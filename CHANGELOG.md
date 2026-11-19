# Changelog

Every package (generator, core, model, host, web and the six MCP servers)
carries the same version. PR-by-PR detail is in
[docs/PROJECT_HISTORY.md](docs/PROJECT_HISTORY.md).

## Unreleased

| Area | What changed |
|---|---|
| Answer card | The gold "What that means" section is gone: it restated the calculated answer and could be mistaken for AI text. The card now has two parts, calculated (green) and added by the AI, then checked (blue). `farm-cli` still prints its "Therefore:" line |
| Home screen | Example questions nest under one "Example questions (5 types)" row; farm description line and the duplicate "When the AI is stopped" group removed (#34) |
| Docs | README shortened from 115 to 57 lines; developer notes moved to [docs/DEVELOPER.md](docs/DEVELOPER.md) (#33) |
| Tests | Host tests never touch the app's own state under `data/` (#32) |
| Season windows | "Last five years" always means the latest five known seasons: years the model picks itself are replaced in code, and a single season the question never names is refused (`season_not_named`) |
| Same cents on every platform | Profit is computed in exact Decimal, revenue and cost settled to the cent like the answer key: a float SUM had put eval 4's Marginal Eighty at -$112,044.66 on a Mac and -$112,044.65 on Linux. Eval 4 tests now expect -$112,044.66; YOUR_RECORDS' worked example is -$16,921.40 |
| Withheld-sentence demo | `test_withheld_sentence_demo` is xfail: it records the model's wording on one machine, not code behaviour |
| Refusal labels | `refusal_kind` is the parser's own kind (`out_of_scope`, `invalid_output`, ...), not a catch-all `unparseable` |
| Eval report | `scripts/run_evals.py` writes each eval question's expected answer next to the app's actual answer |
| Season-count check | A 9th check, `season_count`: an AI sentence that counts years or seasons ("over the past five years") must use a count the records hold, and can't compare a season with the "previous N" that include it |
| Eval 3 Therefore line | No longer repeats the answer's first sentence; it states the verdict ("5 of its 6 recorded seasons had no loss") |
| Eval 9 wording | The eval doc says the app checks the ledger against its own as-applied estimate, which lands near the correct entry, not on it |

## 0.2.0 (November 2026)

The grower web app grows up: follow-up questions, two example farms, all six
MCP servers in the demo, and a "Show the records" view behind every answer.
PRs #15–#31.

| Area | What changed |
|---|---|
| Follow-up questions | Ask a follow-up and the app keeps the subject ("Talking about:" line, "Ask next" buttons); "↺ New subject" starts over (#15, #25) |
| Two example farms | Farm 1 (clean records) / Farm 2 (messy records) picker; Riverside renamed Sheyenne Bottom (#17) |
| All six MCP servers | Weather, soil and as-applied questions now answered (evals 12–15), with a `units` check (#18) |
| Faster answers | MCP servers stay running between questions: about 4 s to about 0.2 s per lookup (#16) |
| Withheld AI sentence | The answer card shows when the AI sentence was withheld; one AI try by default so the demo works with real Gemma (#19, #21) |
| Question box | Each question is sent exactly once (Enter to send, locked while answering); browser tests added (#22) |
| Clearer UI | Slim banner, checks and numbers folded to one line each, bigger text (#25) |
| Show the records | Lists the files, tabs and rows behind each answer (`records_behind` tool); new [docs/YOUR_RECORDS.md](docs/YOUR_RECORDS.md) (#27, #28) |
| Docs | Question-flow diagram in ARCHITECTURE.md; second docs review; multi-turn pairs in EVAL_QUESTIONS.md; README screenshots retaken with real Gemma (#20, #23, #24, #26) |
| CI | One Ubuntu PR check (about 3–4 min, tests run 4 at a time); real-model job manual only; Windows dropped from CI (#29, #30) |

## 0.1.1 (November 2026)

Docs reviewed against the code; all packages, generator included, on one
version (#14). Also includes the grower web app (`farm-web`) (#11–#13).

## 0.1.0 (November 2026)

Eval fix plan P0–P5: answer key matches the raw files, template-first
narration with semantic checks, CLI cleanup for live demos, and tests for all
11 eval questions (#2–#10).
