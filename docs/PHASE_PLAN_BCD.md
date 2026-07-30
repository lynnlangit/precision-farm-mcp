# Precision Farm MCP — Remaining Plan: Phases B, C, D

This is the continuation of the multi-session design-review plan. **Phases
A and B are complete** (see status below). This file preserves the full
B/C/D spec verbatim from the original review so a future session can resume
without re-deriving context. Start a future session by reading this file in
full before planning Phase C.

## Status as of this writing

- **Phase 0** (audit) — done. Found the confirmation gate was inert
  (`auto_approve` default) plus two unprompted findings: the audit hash
  chain was breakable under concurrent writes, and there was no
  provenance/injection defense.
- **Phase 1** (make confirmation real) — done. `farm-ingest` /
  `ConfirmationGate` / versioned `PersistedConfirm` / fail-closed
  `build_farm_snapshot` / `confirmation_required` refusal across all 5
  servers / `DEF-ALIASTIE` generator defect proving the gate changes an
  outcome. All merged and tested.
- **Phase A** (foundations) — done, this session:
  - **A1**: Audit hash chain fixed (cross-platform file lock +
    backward-seek read instead of full rescan). Verified with a real
    multi-process test. Old broken log archived to
    `data/audit.jsonl.pre-a1-fix`; both `data/audit.jsonl` and
    `data/confirmed_mappings.json` are now gitignored (they were committed
    in an earlier session — that content still exists in git **history**;
    purging it would need a history rewrite, not done, ask first if wanted).
  - **A2**: Provenance made structural — every server response reserves a
    `modeled` field (currently always `None`); nothing outside it needs a
    tag, since blending measured/derived was never the risk.
  - **A3**: Grounding check split into measured/derived vs. modeled rates
    (`check_narration_grounded_by_provenance`), proven against a
    hand-built fixture since nothing is modeled yet.
  - **A4**: `MCPFleet.call()` returns `ToolResult(data, untrusted_paths)`;
    untrusted free text is delimited for the prompt and **redacted** for
    grounding (a real vulnerability was found and fixed here: numbers
    quoted inside injected text were being treated as legitimate grounding
    evidence for themselves). `DEF-INJECTION` generator defect proves
    narration is unaffected. Payload capping caps free text first, drops
    whole list entries as a backstop, never truncates serialized JSON.
  - Also fixed along the way: `provenance` (snapshot metadata, e.g.
    `built_at` timestamps) is excluded from grounding entirely — it was
    being number-mined, letting incidental digits "ground" almost anything.
  - 93 tests green across 4 packages (generator 10, core 39, host 26,
    model 18). README updated: new intro + example + architecture diagram
    reflecting the ingest/query split, confirmation gate, audit log, and
    untrusted-text boundary. README's diagram later simplified for a
    farmer audience; the detailed diagram moved to `docs/ARCHITECTURE.md`.
- **Phase B** (metrics + architecture doc) — done, this session:
  - **B1**: `core/src/farm_core/metrics.py` (pure functions) +
    `farm-metrics` CLI, reporting HITL catch rate, tool grounding (2
    rates), narration faithfulness, and sovereignty integrity from
    `AuditLog.entries()`. Found along the way: two of the four metrics had
    no data to read — `narrate_verified()` already computed grounding and
    attempt/fallback info but the `narration` audit event only logged
    `question`. Fixed by adding `attempts_used`/`used_fallback` to
    `NarrationOutcome` and enriching the `narration` event with
    `grounded`/`modeled_grounded`/`attempts`/`used_fallback`. Every rate is
    `null` (not `0`) when its denominator is zero; legacy narration events
    predating this change are counted and excluded, not miscounted.
    `network_calls_attempted` is reported as a structural `0` citing
    `test_no_network.py`'s two checks, not literally tallied from the
    audit log (nothing there could ever produce a nonzero count).
  - **B2**: `docs/ARCHITECTURE.md` gained a built/deferred/diverged
    component table, a roadmap table, and a "known future tensions"
    section recording the weather/sync-boundary trade-off before Phase C
    needs it. `docs/test_architecture_doc.py` (standalone, no project venv
    needed) asserts the diagram's server list matches `servers/`.
  - Found and fixed a real, pre-existing, order-dependent bug in
    `host/tests/test_no_network.py`'s own fixture while adding a new
    live-Ollama test: `ollama.chat` is a bound method captured once at
    import time, so a connection warmed by an earlier live-Ollama test in
    the same run gets reused rather than reconnected, making the
    fixture's own sanity check fail with no real non-loopback connection
    ever happening. Fixed by rebinding to a fresh `Client().chat` in the
    fixture — the actual security assertion (`assert not non_local`) was
    never touched or weakened.
  - 106 tests green across 4 packages (generator 10, core 50, host 28,
    model 18), plus `docs/test_architecture_doc.py` passing standalone.

**Not yet started: Phases C, D below.** Per the working agreement, check
in for approval before starting Phase C, and again before D.

---

## Working agreement (unchanged, applies to B/C/D)

- Reuse before rebuilding, and say what you're reusing.
- Present plans, options, and findings as tables.
- Check in for approval between phases. Do not begin the next one
  unprompted.
- Do not run destructive operations.
- If a phase turns out to be badly scoped once inside it, stop and say so
  rather than working around it.
- No new dependencies without asking — a heavy geospatial/scientific stack
  temptation in Phase C or D must be proposed and approved first.

## Acceptance criteria across all phases

- All existing tests stay green, except numbers regenerated under C2,
  which must be regenerated (not hand-edited).
- New tests required: multi-process audit chain (done, Phase A), provenance
  enforcement (done, Phase A), injection defect (done, Phase A), attribution
  distinguishing weather from management (Phase C), zone refusals (Phase D).
- `test_no_network.py` stays unchanged and unweakened, including through
  Phase C's synthetic weather.
- The Phase B metrics command runs end to end and emits a report.

---

## PHASE B — Metrics and one canonical architecture document

### B1 — Governance metrics harness

Now computable for the first time, because Phase 1 made confirmations real
and Phase A made the audit log trustworthy and the grounding check
provenance-aware. One command, JSON report, derived from the audit log.

| Metric | Definition |
|---|---|
| HITL catch rate | Proportion of confirmation proposals the human corrected or rejected |
| Tool grounding | Two rates per A3: measured/derived, and modeled |
| Narration faithfulness | Existing verification checks expressed as rates, not pass/fail |
| Sovereignty integrity | Exports performed, fields redacted, network calls attempted (must be zero) |

These are paper artifacts. State each definition precisely in code, make
them stable across runs, and report them over a full run against the
synthetic data. If a definition is ambiguous, say so and propose wording
rather than picking silently. Reuse: `AuditLog.entries()`,
`check_narration_grounded_by_provenance`, `governance.ConfirmationGate`'s
event log (`confirmation_accepted`/`corrected`/`refused`).

### B2 — docs/ARCHITECTURE.md

`docs/` currently holds only `EVAL_QUESTIONS.md` (and now this file), and
the README mermaid diagram is the sole architecture diagram.

- One mermaid diagram of the full target architecture, every component
  marked built, deferred, or diverged.
- `diverged` entries carry one line explaining why the build differs from
  the design, so deviation is a recorded decision rather than drift.
- A roadmap table mapping each deferred component to the phase that needs
  it: remote sensing, agronomy refs, the prescriptive crop model, and the
  sync boundary are all deferred deliberately.
- Record explicitly under known future tensions: weather is synthetic in
  Phase C precisely so that `test_no_network.py` stays intact. Live weather
  would require a sync boundary and would weaken "no outbound network" to
  "no network at query time." That's a real future divergence, written
  down now, not discovered later. Do not weaken the test in this build.
- Add `docs/test_architecture_doc.py` asserting the servers listed in the
  document exactly match the directories under `servers/`, so the doc
  can't go stale without a test failing.

**Stop. Wait for approval before Phase C.**

---

## PHASE C — The world model, aimed backwards

`bad_field_or_bad_year` currently returns a verdict with no cause. It can
say a season was an outlier at N MADs below median; it can't say why,
because the causal variable was never ingested (weather).

This phase adds attribution, not prediction. Retrospective explanation
validates against ten seasons already known; prediction validates at one
data point per year. Same machinery, and the retrospective version is a
prerequisite for the prescriptive one anyway.

### C1 — Weather is generated, not downloaded

Synthetic weather is not a stopgap. With real weather the true
decomposition of a shortfall is unknowable, so an attribution claim is
unfalsifiable. With generated weather it's known exactly, because the
generator caused it — that's what makes this phase testable at all, and it
keeps `test_no_network.py` fully intact.

Add to the generator:
- Daily weather per season: precipitation, min/max temperature. Realistic
  autocorrelation across days, shared across fields on the farm (one farm
  sees roughly one weather).
- A static soil available-water-capacity per field — what makes shared
  weather affect fields differently, separating a bad field from a bad
  year.
- Yields derived from weather, soil capacity, and management, rather than
  drawn independently. Weather must cause yield or attribution has nothing
  real to recover.

### C2 — Regeneration, deliberately

C1 changes the numbers. `ground_truth.json` and `docs/EVAL_QUESTIONS.md`
both need regenerating — accepted.

What must not change is the narrative. Pin the qualitative fixtures in
config and assert them: Marginal Eighty stays chronically unprofitable,
East 80 keeps exactly one outlier season, `DEF-ALIASTIE` still fires, the
coverage gap still exists. Same stories, new numbers. Regenerate
`EVAL_QUESTIONS.md` from `ground_truth.json` rather than hand-editing it,
so it can't drift again. (`host/tests/test_eval_questions.py` and
`README.md`'s Q4 figures will also need a refresh — this already happened
once this session when `DEF-ALIASTIE` changed Section Corner's true
acreage; the same regenerate-and-recheck workflow applies here, at larger
scale.)

### C3 — Two shortfalls that must be told apart

Inject two separate causes, each with a defect ID and the true
decomposition recorded in `ground_truth.json`:
- One field-season where the shortfall is weather-caused.
- One field-season where the shortfall is management-caused, with normal
  weather — late application, or a rate well below plan.

The test for this whole phase is whether attribution distinguishes them.
If it can't, the world model is decorative — find that out before building
on it.

### C4 — The model itself

- New server, `weather-history`, reading the generated files. Offline, no
  network, no exception to the existing test.
- `core/expectation.py`: a water and heat balance producing an expected
  yield per field-season. Relative expectation, not absolute — avoids
  needing cultivar calibration, and it's all attribution requires.
- Variance decomposition: season effect (weather, shared), field effect
  (soil, persistent), residual (management and noise).
- `bad_field_or_bad_year` gains the decomposition, under the `modeled`
  subtree A2 already reserved for exactly this. Propose whether it
  replaces `LOSS_RATE_BAD_FIELD_THRESHOLD` and `OUTLIER_MAD_MULTIPLIER` or
  supplements them, with reasoning — those constants are currently
  arbitrary and a derived decomposition is a stronger basis, but argue it,
  don't silently swap it.
- New query intent for the "why" question, wired through the fixed schema
  menu (`query_schema.py`'s `QueryIntent`).
- Every output tagged `modeled` per A2 (this is the seam A2/A3 were built
  for). Calibration state is a first-class field. Refuse rather than
  estimate where weather coverage or seasons are insufficient.
- Backtest across all ten seasons and report error. Publish it in the
  Phase B metrics report; don't hide it.

**Stop. Wait for approval before Phase D.**

---

## PHASE D — Zone-level profitability

`yield_monitor_points` and `as_applied_events` both carry lat/lon, and
nothing consumes them spatially — `crs.py` converts coordinates,
`reconciliation.py` bins longitude to find coverage gaps, and that's the
whole of it. Sub-field data has been sitting in DuckDB unused since ingest
was written.

- Grid each field into management zones; join yield points to as-applied
  events spatially within zone and season.
- Zone-level profit for the four seasons that have as-applied coverage.
  Refuse for the six that don't, rather than extrapolating.
- Refuse on insufficient point coverage within a zone, in the same shape
  as the existing coverage-gap logic (`reconciliation.py`'s
  `coverage_gap_flagged`).
- Add a generator case: a genuinely unprofitable zone inside an otherwise
  profitable field, recorded in `ground_truth.json`.
- Report the headline figure — what share of acres lose money inside
  profitable fields.

This is derived arithmetic, not modeled, and should be tagged accordingly
(outside the `modeled` subtree).

Deliberately last: highest farmer-perceived value, lowest technical risk,
no trust-contract change, and needs nothing from B or C.

---

## Where to resume

Start a new session with: *"Read docs/PHASE_PLAN_BCD.md, then start with a
Phase C plan only"* — this mirrors how Phases A and B were kicked off (plan
first, `ExitPlanMode` for approval, then implement C1 → C2 → C3 → C4 in
order, stopping for approval before D).
