# Architecture

The technical design behind Precision Farm MCP. For the short,
farmer-facing picture, see the [README](../README.md#how-it-works).

```mermaid
flowchart TD
    Farmer(("Farmer"))

    Farmer -->|"once, interactively,<br/>per new/changed data"| Ingest["farm-ingest"]
    Farmer -->|"any question, in the browser"| Web["farm-web<br/>local web app for growers<br/>Farm 1 / Farm 2 picker, follow-ups"]
    Dev(("Developer")) -->|"any question, in the terminal"| CLI["farm-cli"]

    Ingest --> Gate["ConfirmationGate<br/>propose → human confirms → persist"]
    Gate --> Store[("confirmed_mappings*.json, one per farm<br/>versioned — a correction appends,<br/>never overwrites")]
    Gate -.-> Audit

    Web -->|"same answer_question() path"| Parser
    CLI --> Parser["Gemma 3:4b<br/>question → validated query — nothing else"]
    Parser --> Router["MCP client / tool router<br/>stdio child processes, no network;<br/>the web app keeps them running"]

    subgraph Servers["MCP servers — non-interactive, query-time, fail closed"]
        FR["field-registry"]
        YH["yield-history"]
        AA["as-applied"]
        CL2["cost-ledger"]
        RE["report-export"]
        WH["weather-history"]
    end

    Router --> Servers
    Store -->|"read-only —<br/>a server can never prompt a human"| Servers
    Servers -->|"unconfirmed ⇒ confirmation_required<br/>refusal, never a guess"| Router
    Servers --> DB[("DuckDB — 10 seasons, local files only")]
    Servers -.-> Audit[("audit.jsonl<br/>hash-chained — safe under concurrent<br/>host + server process writes")]

    Router --> Template["Template answer<br/>deterministic lead sentence + 'therefore' line"]
    Router --> Narrator["Gemma 3:4b<br/>may add one sentence of context. Farmer free text<br/>is delimited as untrusted data first"]
    Narrator --> Checks["Verifier — 8 checks<br/>grounded numbers, verdict, 6 meaning checks —<br/>one try — fails ⇒ sentence withheld"]
    Template --> Answer(["Answer<br/>the web app also shows the checks, figures and source"])
    Checks -->|"only if every check passes"| Answer
```

Gemma touches a question at exactly two points: parsing it into a
validated query, and adding at most one sentence to an answer a
deterministic template has already written. That sentence is shown only if
it passes all 8 checks in `model/src/farm_model/verification.py`;
otherwise it is withheld and the template answer stands alone. Gemma never
sees raw data, computes a number, or resolves an ambiguous name; the model
layer can't import a database or MCP client
(`model/tests/test_model_bounded.py`).

Confirmation is structural. A server can't prompt a human, so `farm-ingest`
confirms and persists every alias, event and mapping once, with a human
present; servers read that record and refuse (`confirmation_required`)
rather than guess. Every decision lands in one hash-chained,
concurrency-safe audit log. Ledger notes reaching Gemma are delimited as
untrusted, excluded from grounding, and never followed as instructions,
proven against an injected-prompt defect.

## How a question flows in the web app

Built from `web/src/farm_web/app.py`, `host/src/farm_host/cli.py` and
`model/src/farm_model/narrator.py`. Edit this block when that flow changes.

```mermaid
sequenceDiagram
    autonumber
    actor G as Grower
    participant W as Web app<br/>(browser page)
    participant H as Farm host<br/>(plain code)
    participant AI as AI model<br/>(Gemma 4B on Ollama)
    participant S as Farm record servers<br/>(6 MCP servers)
    participant C as The 8 checks<br/>(plain code)

    rect rgb(246, 233, 200)
    Note over W,S: When the app opens (once)
    W->>S: Start Farm 1's six servers in the background (about 7 s)
    S->>S: Load the farm's records into an in-memory DuckDB copy
    Note over S: Servers stay running, so each lookup takes about 0.2 s
    end

    rect rgb(232, 240, 228)
    Note over G,S: "Whose records?" picker (optional)
    G->>W: Pick Farm 1 (clean records) or Farm 2 (messy records)
    W->>S: Start that farm's servers, the first time it is picked
    W->>W: Forget the follow-up context (it came from the other farm)
    W->>W: Ask the same question again, so the two farms can be compared
    end

    Note over G,C: Asking a question
    G->>W: Type a question and press Enter or "Ask my records",<br/>or tap an example or an "Ask next" button
    W->>W: Send it once, then lock the box and buttons ("Looking it up...") until the answer is shown
    W->>H: The question + which farm + follow-up context<br/>(last field, season, question type)
    H->>AI: Turn this question into ONE lookup
    AI-->>H: Question type + field + season (structured JSON)
    alt AI not running, question out of scope, or a follow-up's field/season came from nowhere
        H-->>W: Polite "I couldn't look that up" — nothing is looked up
    end
    H->>H: Pick the one server and tool for that question type (a fixed table, not AI)
    H->>S: One lookup, e.g. bad_field_or_bad_year("East 80")
    S-->>H: Numbers straight from the records (no AI involved)
    alt Records can't answer (unknown field, missing season)
        H-->>W: The server's reason, shown to the grower
    end
    H->>H: Write the verified answer from a template using only those numbers
    H->>AI: Add at most one sentence of context?<br/>(sees the question, the verified answer, the numbers)
    AI-->>H: One sentence (or "NONE" — nothing to add)
    H->>C: Run the 8 checks on the AI's sentence
    Note over C: 1 Every number appears in your records<br/>2 Agrees with the verified answer<br/>3 Gains are gains, losses are losses<br/>4 Describes the right zones<br/>5 Says correctly whether two records agree<br/>6 Doesn't treat a modeled estimate as a proven cause<br/>7 Doesn't name a cause your records don't show<br/>8 Every number keeps its own unit
    alt All 8 pass
        C-->>H: Passed — sentence is SHOWN, tagged "Added by the AI, then checked"
    else Any check fails
        C-->>H: Failed — sentence is WITHHELD (no second try), the verified answer stands alone
    end
    H->>H: Add the "therefore" line and write every step to the audit log
    H-->>W: Answer + checks + numbers + source
    W-->>G: Answer with farm badge, "How we checked it",<br/>"The numbers behind it", "Where it came from"

    rect rgb(232, 236, 246)
    Note over G,W: Follow-ups
    W->>W: Remember field, season and question type (only from a verified answer)
    W-->>G: Up to 3 "Ask next" buttons — each is a full new question, checked from scratch
    G->>W: "Clear" forgets the context and starts over<br/>(an answer still on its way is dropped)
    Note over G,W: Asking the same question again repeats it exactly,<br/>not as a follow-up to its own answer
    end
```

## Component status

| Component | Status | Note |
|---|---|---|
| Ingest/query confirmation split, `ConfirmationGate` | Built | |
| 6 MCP servers, `farm-cli`, `farm-ingest` | Built | Every server has at least one question type routed to it |
| Weather, soil and as-applied questions | Built | `SEASON_WEATHER`, `FIELD_SOIL` (`weather-history`) and `APPLIED_INPUTS`, `NITROGEN_HISTORY` (`as-applied`), computed in `core/field_conditions.py`. Nitrogen is always reported in lb N/ac, converting gal/ac of UAN 32%; corn and soybean N are never compared. A `units` check rejects a sentence that puts the wrong unit on a number. These are records, not causes: none of them says why a season went badly |
| Grower web app (`farm-web`, `web/`) | Built | Thin Gradio layer over `farm_host.cli.answer_question`, so it can't drift from the CLI or evals. Shows the template sentence, the checked AI sentence or a "withheld" note, the checks, figures and source. The "When the AI is stopped" example, "Was East 80 a bad field or just a bad year?" (eval 2), shows a withheld sentence: gemma3:4b blames the weather, which no record supports. `NARRATION_SEED` makes it repeatable on a given machine; `scripts/probe_narration.py` re-checks it against the real model. Local only unless `--lan` |
| Persistent servers (`farm_host.server_pool`) | Built | All six servers start once in the background (~7 s) and stay up, so a lookup takes ~0.2 s instead of ~4 s. Restart the app after regenerating data |
| Farm picker (`farm_host.farms`) | Built | Farm 1: clean records (`data/synthetic-clean`, generator `--clean`). Farm 2: messy records (`data/synthetic`). Same fields and true profits. One server pool per farm via `FARM_DATA_DIR`/`FARM_CONFIRM_STORE`; Farm 1 starts at app open, Farm 2 on first pick. Switching clears follow-ups and re-asks the question; every answer carries a farm badge |
| Follow-ups (`farm_host.followups`) | Built | Only the last verified answer's field, season and question type carry over; the parser refuses a follow-up whose field or season came from nowhere. A "Showing:" line names what was answered, plus up to 3 "Ask next" buttons |
| Template-first narration (`narrate_verified`) | Built | Template sentence always leads; the model may add one sentence, kept only if it passes all 8 checks (grounded, verdict, sign, zone premise, reconciliation, attribution, unsupported cause, units). One try by default (`max_attempts=1`), so a failing sentence is withheld, not rewritten |
| Hash-chained, concurrency-safe audit log | Built | Host and every server write to it (fixed in Phase A) |
| Provenance (`modeled` subtree), grounding split | Built | `modeled` is filled by weather attribution on `bad_year` verdicts, `null` elsewhere by design |
| Untrusted-text handling, payload capping | Built | |
| Governance metrics (`farm-metrics`) | Built | Includes an `attribution_backtest` section |
| Weather ingestion, attribution model | Built | Synthetic weather + soil AWC (`weather-history`); `core/expectation.py` splits a shortfall into `season_effect` and `residual`; `EXPLAIN_SHORTFALL` intent |
| Zone-level (sub-field) profitability | Built | `core/zone_profitability.py`, 2x2 zones per field, as-applied seasons only |
| Readiness check (`farm-preflight`) | Built | Checks uv, Ollama, model, data and ingest, then runs a live query |
| Non-interactive ingest (`--auto-approve-synthetic-only`) | Built | Refused outside `data/synthetic/`; DEF-ALIASTIE shows why it must never touch real records |
| Model-free query path (`farm-cli --intent`) | Built | No `ollama.chat` call anywhere on this path (`test_structured_path_never_calls_ollama`) |
| Deterministic "therefore" line (`therefore.py`) | Built | Template-built, omitted where there is no verdict to restate |
| Clear failures (`ParseFailure.kind`, exit codes) | Built | A dead model and an out-of-scope question get different messages; CLIs exit 1 on any refusal |
| CI (`.github/workflows/tests.yml`) | Built | PRs: `generator`+`core` on Ubuntu and Windows. Nightly/manual: `host`+`model` with real Ollama on Ubuntu. Docs-only changes skip CI; `web` and the docs test run locally |
| **Diverged:** confirmation at query time | — | MCP servers can't prompt a human, so confirmation moved to ingest |
| **Diverged:** zone cost is field-uniform | — | The data has no per-zone cost (ledger is per acre), so only yield is zone-resolved |
| Remote sensing | Deferred | Out of scope by design; not scheduled |
| Agronomy reference data | Deferred | Only needed if an absolute (not relative) expectation model is ever required |
| Prescriptive crop model / recommendations | Deferred | Out of scope (see README); not scheduled |
| Live weather / any sync boundary | Deferred | Not scheduled; see below |

## Known future tensions

**Weather is synthetic, on purpose.** With real weather the true split of
a shortfall is unknowable, so an attribution claim would be unfalsifiable.
With generated weather it's known exactly: forcing one season into drought
is correctly attributed to weather, not management
(`core/tests/test_expectation.py`).

Live weather would need a sync boundary and would weaken "no outbound
network" to "no network at query time". **`host/tests/test_no_network.py`
is not weakened in this build**; any change that touches it should update
this section first.

## See also

- [README](../README.md) — the simple picture, quick start, and repository layout
- [FARMER_GUIDE.md](FARMER_GUIDE.md) — plain-language setup and usage guide
- [VERIFICATION.md](VERIFICATION.md) — how to run the tests and what they prove
- [EVAL_QUESTIONS.md](EVAL_QUESTIONS.md) — fifteen independent evaluation questions
- [PROJECT_HISTORY.md](PROJECT_HISTORY.md) — the phase history
