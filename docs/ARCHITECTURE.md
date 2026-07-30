# Architecture

The technical design behind Precision Farm MCP. For the short,
farmer-facing picture, see the [README](../README.md#how-it-works).

```mermaid
flowchart TD
    Farmer(("Farmer"))

    Farmer -->|"once, interactively,<br/>per new/changed data"| Ingest["farm-ingest"]
    Farmer -->|"any question, any time"| CLI["farm-cli"]

    Ingest --> Gate["ConfirmationGate<br/>propose → human confirms → persist"]
    Gate --> Store[("confirmed_mappings.json<br/>versioned — a correction appends,<br/>never overwrites")]
    Gate -.-> Audit

    CLI --> Parser["Gemma 3:4b<br/>question → validated query — nothing else"]
    Parser --> Router["MCP client / tool router<br/>stdio child processes, no network"]

    subgraph Servers["MCP servers — non-interactive, query-time, fail closed"]
        FR["field-registry"]
        YH["yield-history"]
        AA["as-applied"]
        CL2["cost-ledger"]
        RE["report-export"]
    end

    Router --> Servers
    Store -->|"read-only —<br/>a server can never prompt a human"| Servers
    Servers -->|"unconfirmed ⇒ confirmation_required<br/>refusal, never a guess"| Router
    Servers --> DB[("DuckDB — 10 seasons, local files only")]
    Servers -.-> Audit[("audit.jsonl<br/>hash-chained — safe under concurrent<br/>host + server process writes")]

    Router --> Narrator["Gemma 3:4b<br/>result → plain language. Farmer free text is<br/>delimited as untrusted data first — nothing else"]
    Narrator -->|"plain-language answer"| Answer(("Farmer"))
```

Gemma touches a question at exactly two points — parsing it into a
validated query, and narrating a computed result. It never sees raw data,
computes a number, or resolves an ambiguous name itself; the model layer
can't import a database or MCP client (`model/tests/test_model_bounded.py`).

Confirmation is structural. A server can't prompt a human, so `farm-ingest`
confirms and persists every alias, event, and mapping once, with a human
present; servers read that record, refusing (`confirmation_required`)
rather than guessing. Every decision lands in one hash-chained,
concurrency-safe audit log. Ledger notes reaching Gemma are delimited as
untrusted, excluded from grounding, and never followed as instructions —
proven against an injected-prompt defect.

## See also

- [README](../README.md) — the simple picture, quick start, and repository layout
- [EVAL_QUESTIONS.md](EVAL_QUESTIONS.md) — ten independent evaluation questions
- [PHASE_PLAN_BCD.md](PHASE_PLAN_BCD.md) — the remaining roadmap
