# Changelog

Every package (generator, core, model, host, web and the six MCP servers)
carries the same version. PR-by-PR detail is in
[docs/PROJECT_HISTORY.md](docs/PROJECT_HISTORY.md).

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
