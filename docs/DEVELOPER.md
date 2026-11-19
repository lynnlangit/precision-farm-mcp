# Developer notes

For the overview and quick start, see the [README](../README.md). How the
pieces fit together is in [ARCHITECTURE.md](ARCHITECTURE.md), and how it is
tested is in [VERIFICATION.md](VERIFICATION.md).

## Quick start notes

- Every query refuses until `farm-ingest` has run for that farm: MCP servers
  can't ask a human, so each name, field change and column mapping is
  confirmed once up front. `--auto-approve-synthetic-only` is allowed only
  for the example data, whose answers are already known.
- Regenerating Farm 2's data also rewrites [EVAL_QUESTIONS.md](EVAL_QUESTIONS.md).
  Restart `farm-web` afterwards, because it keeps its servers running
  between questions.
- `farm-web --lan` shares the app on the local Wi-Fi. It is local only
  otherwise.

## farm-cli

`farm-cli` is the developers' interface. It answers through the same code
as the web app and adds a model-free `--intent` path that prints the raw
JSON result (`farm-cli --list-intents`).

```bash
uv run --project host farm-cli "was the north eighty a bad field or a bad year"
uv run --project host farm-cli --version
```

![farm-cli answering "was the north eighty a bad field or a bad year" on a Mac](images/farm-cli-example.png)

## Commands and settings

| Command | What it does |
|---|---|
| `farm-ingest` | Confirms names, field changes and column mappings once, with a human present |
| `farm-preflight` | Checks uv, Ollama, the model, the data and ingest, then runs a live query |
| `farm-web` | The grower web app (`--port`, `--lan`, `--no-browser`) |
| `farm-cli` | One question in the terminal; `--intent` skips the model |
| `farm-metrics` | Governance report from the audit log (`--out` writes it to a file) |
| `scripts/probe_narration.py` | Asks questions through the real model and prints what each check did |
| `scripts/run_evals.py` | Asks every [eval question](EVAL_QUESTIONS.md) through the real model and writes `data/eval_results.md`: expected answer, tool called and actual answer side by side (`1 7 F2` runs just those; `--farm farm1`) |

The MCP servers read these settings from the environment. The web app
sets the first two per farm, and `farm-cli --audit-log` sets the third.

| Setting | Default |
|---|---|
| `FARM_DATA_DIR` | `data/synthetic` (Farm 2) |
| `FARM_CONFIRM_STORE` | `data/confirmed_mappings.json` |
| `FARM_AUDIT_LOG` | `data/audit.jsonl` |
| `FARM_SERVER_START_TIMEOUT` | 120 seconds (the first start builds each server's environment) |

## Repository layout

| Path | What it is |
|---|---|
| `generator/` | Synthetic-data generator: 10 seasons, 12 fields, every defect (naming drift, splits/merges, sensor calibration error, messy spreadsheets) injected on purpose and recorded in `ground_truth.json`; also writes [EVAL_QUESTIONS.md](EVAL_QUESTIONS.md) |
| `core/` (`farm_core`) | Shared library: DuckDB ingestion, field identity, reconciliation, profitability, audit log, governance |
| `servers/mcp-*` | Six FastMCP servers exposing `farm_core` as read-only MCP tools |
| `host/` (`farm_host`) | MCP client and router, `farm-ingest` (human confirmation), `farm-cli`, `farm-preflight`, `farm-metrics` |
| `web/` (`farm_web`) | `farm-web`, the local Gradio app for growers, a thin layer over `farm_host` |
| `model/` (`farm_model`) | The bounded Gemma layer: question to lookup, the one added sentence, and the 9 checks |
| `scripts/` | `probe_narration.py` and `run_evals.py`, for checking questions against the real model |
| `data/` | The example farms once generated (`synthetic/`, `synthetic-clean/`), confirmed mappings and the audit log; all gitignored except `data/synthetic/README.md` |
| `docs/` | Every doc is listed in the [README](../README.md#start-here) |
