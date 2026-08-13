# Precision Farm MCP — Plan: Phases B, C, D

This is the continuation of the multi-session design-review plan. **All
phases (A, B, C, and D) are complete** (see status below). This file
preserves the full B/C/D spec verbatim from the original review, plus the
full status history, so a future session can resume without re-deriving
context.

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
- **Phase C** (the world model, aimed backwards) — done, this session:
  - **C1**: `generator/src/farm_data_gen/weather.py` — one AR(1)-
    autocorrelated daily weather series per season (precip, temp min/max),
    shared across every field active that season. `economics.
    assign_soil_awc` gives each field a static AWC draw; yield became
    causal (water deficit buffered by AWC, plus a small heat penalty, on
    top of the existing baseline draw). Found and fixed along the way: the
    original `CATASTROPHIC_YIELD_FACTOR` (0.25) no longer safely dominated
    once weather added its own profit variance — tightened to 0.10, and
    `stress_yield_k`/`min_yield_multiplier` tuned so ordinary weather
    variance stays real but doesn't spuriously trigger the MAD-outlier rule
    on its own (verified empirically against seed=42).
  - **C3**: `DEF-WEATHERSHORTFALL` (a forced-drought season, shared farm-
    wide) and `DEF-MGMTSHORTFALL` (a direct management-multiplier override
    under ordinary weather), both structurally guaranteed regardless of
    seed. Recorded in `ground_truth.json` both as defect records and as
    top-level `weathershortfall`/`mgmtshortfall` keys.
  - **C2**: Qualitative fixtures pinned and asserted
    (`generator/tests/test_qualitative_fixtures.py`): Marginal Eighty still
    chronically unprofitable, East 80 still exactly one outlier season,
    `DEF-ALIASTIE`/`DEF-INJECTION` still fire, the coverage gap still
    exists. `generator/src/farm_data_gen/eval_questions.py` now generates
    `docs/EVAL_QUESTIONS.md` from `ground_truth.json` (never hand-edited
    again); its field selections are computed dynamically, not hardcoded,
    after forcing drought onto the field the old doc used as its "boring"
    negative-control example changed that field's own story.
    `host/tests/test_eval_questions.py` and the README CLI-mockup screenshot
    refreshed against the regenerated data.
  - **C4**: `core/src/farm_core/expectation.py` — a *relative* expectation
    model (no cultivar calibration): `expected_yield = field's own average
    × weather_multiplier(season, AWC)`, decomposed into `season_effect`
    (weather-driven) and `residual` (unexplained). New `mcp-weather-history`
    server. `bad_field_or_bad_year` gains `modeled.attribution` for
    `bad_year` verdicts (one entry per outlier season) — the verdict itself
    is unchanged, attribution only ever supplements it. New
    `QueryIntent.EXPLAIN_SHORTFALL` for "why" questions, routed to the same
    tool. `farm-metrics` gained an `attribution_backtest` section
    (MAE/RMSE over every attributable field/season, published not hidden).
  - Found and fixed a real bug in `verification.
    check_narration_grounded_by_provenance` while wiring C4 end to end: a
    narration correctly citing one real number from `evidence` and one real
    number from `modeled` in the same sentence — exactly what an attribution
    narration does — failed *both* grounding channels, because each channel
    only recognized its own numbers. Never caught earlier because `modeled`
    was always `None` before Phase C, so no narration could ever have
    exercised this path. Fixed so a number grounded in either channel is
    never counted against the other; only a genuine fabrication (grounded
    in neither) fails a channel — `host/tests/test_metrics_cli.py`'s real-
    question test caught it live.
  - `docs/ARCHITECTURE.md` updated: weather ingestion/attribution moved
    Deferred → Built, `weather-history` added to the server diagram, the
    "known future tensions" section's synthetic-weather rationale confirmed
    (not just planned).
  - 130 tests green across 4 packages (generator 16, core 59, host 34,
    model 20), plus `docs/test_architecture_doc.py` passing standalone.
    `test_no_network.py` unchanged and unweakened.
- **Phase D** (zone-level profitability) — done, this session:
  - **Key finding that reshaped the design**, checked against the actual
    generated data before writing any code: `as_applied_events` has no
    real spatial resolution to join against (5 rows per field/season, one
    per product, each a single decorative lat/lon with an already
    field-wide rate). The spec's literal "join yield points to as-applied
    events spatially" wasn't viable. Resolution: cost genuinely has no
    spatial resolution anywhere in this data model (ledger rows are
    `cost_basis: "per_acre"`, uniform by construction), so zone cost
    reuses the field's own authoritative `total_cost/acres`
    (`profitability.ProfitRecord`) uniformly across every zone; only
    yield is actually zone-resolved, from `yield_monitor_points`'
    hundreds of real per-point readings. Recorded as a `Diverged` row in
    `docs/ARCHITECTURE.md`, stated plainly, not silently reinterpreted.
  - New `core/src/farm_core/zone_profitability.py`: fixed 2x2 zone grid
    (exact, since field boundaries are confirmed axis-aligned
    rectangles); `compute_zone_profitability(snapshot, canonical_id,
    season)` refuses (`ZoneProfitabilityUnavailable`) for an unknown
    field or a season without as-applied coverage (discovered from the
    data, never hardcoded); a zone with fewer than `ZONE_MIN_POINTS`
    yield-monitor points is reported `available: false`, never
    estimated, alongside sibling zones that do have enough points.
    `unprofitable_zones_in_profitable_fields(snapshot)` is the headline
    figure: of the acres in fields genuinely profitable overall that
    season, what share sat in a zone with negative zone-level profit.
  - Two new tools on the existing `mcp-report-export` server (no new
    server needed — Phase D's spec, unlike Phase C's, didn't call for
    one): `zone_profitability` and `unprofitable_zones_in_profitable_
    fields`.
  - New `QueryIntent.ZONE_PROFITABILITY` and `.UNPROFITABLE_ZONES_IN_
    PROFITABLE_FIELDS` — two distinct intents/tools, not one tool with
    two phrasings like Phase C's `EXPLAIN_SHORTFALL`, since these are
    genuinely different computations (per-field detail vs. farm-wide
    aggregate), not two phrasings of the same lookup. Verified live
    against gemma3:4b that the new prompt bullets don't regress the
    existing field-level intents' disambiguation (the exact kind of
    prompt-length regression Phase C hit once and fixed by keeping each
    bullet short and explicit).
  - New generator defect `DEF-BADZONE`: `root_12` ("Section Corner"),
    season 2024, zone 0 — the one clean, unclaimed field/season inside
    the as-applied window. Mechanism: bias the already-generated
    yield-monitor point weights downward for points in the target zone,
    before the existing per-point weight normalization — since that
    normalization already conserves the field's total monitor bushels
    regardless of point placement, the field's total yield/revenue/
    profit is automatically unchanged; only the within-field
    distribution shifts. Verified: zone 0 shows a genuinely negative
    profit (~-$11,944) while the field's total profit stays positive and
    exactly matches the no-defect figure (~$5,896).
  - Found and fixed a real gap while running the full suite: the A4
    completeness test (`test_every_response_model_string_field_is_
    classified`) correctly caught that the new `unavailable_reason`
    field wasn't classified in `farm_host/mcp_client.py` — added to
    `DETERMINISTIC_STRING_FIELDS` (a fixed small set of reason codes,
    never farmer-authored text).
  - New eval question (#11): kept deliberately sign-only, not a dollar
    figure — zone-level numbers are computed by `farm_core.
    zone_profitability` from raw points at query time, not stored in
    `ground_truth.json`, so `generator/eval_questions.py` can't honestly
    reproduce them without depending on `farm_core` (forbidden) or
    duplicating the point-grid arithmetic (fragile).
  - `docs/ARCHITECTURE.md` updated: zone-level profitability moved
    Deferred → Built, the as-applied-spatial-resolution finding recorded
    as a `Diverged` row, roadmap table updated; also fixed two stale
    counts left over from Phase C ("5 MCP servers" → 6, in both
    `ARCHITECTURE.md` and the main `README.md`).
  - 150 tests green across 4 packages (generator 16, core 73, host 39,
    model 22), plus `docs/test_architecture_doc.py` passing standalone.
    `test_no_network.py` unchanged and unweakened — no new server, no new
    network surface.

**All phases complete.** No further phase is planned; per the original
spec, Phase D was deliberately last (highest farmer-perceived value,
lowest technical risk, no trust-contract change).

## Post-phase: workshop preparation

Not a new lettered phase (general-purpose changes only, no workshop- or
org-specific content in this repo) — a targeted round preparing the tool
for a half-day hands-on farmer workshop, where installation has to happen
before the day, not during it:

- `ParseFailure.kind` distinguishes a dead Ollama/unpulled model from a
  genuinely out-of-scope question, with a correctly-targeted message for
  each (`model/src/farm_model/query_parser.py`, `host/src/farm_host/cli.py`).
- `farm-cli`/`farm-ingest` exit non-zero on any refusal, not just 0 always
  (`AnswerResult(text, ok)`).
- `farm-preflight`: a new console script checking `uv`, Ollama, the model,
  the example data, and `farm-ingest` having run, then a live end-to-end
  query — one command instead of five separately confusing failures.
- `farm-cli --intent`: a model-free query path, structured args in, raw
  JSON out, zero `ollama.chat` calls anywhere in it — a live-demo fallback
  if Ollama hiccups mid-workshop.
- `farm-ingest --auto-approve-synthetic-only`: reuses the existing
  `confirm.auto_approve`, structurally refused outside `data/synthetic/`.
- A deterministic "therefore" line appended after a successful answer,
  template-built and omitted (not invented) where no verdict exists to
  restate.
- `.github/workflows/tests.yml`: `generator`+`core` on `ubuntu-latest` and
  `windows-latest`; `host`+`model` (real Ollama calls) on `ubuntu-latest`
  only — see `docs/ARCHITECTURE.md`'s CI row for why the split.
- `docs/FARMER_GUIDE.md`: install path leads with a no-git ZIP download,
  Windows paragraph states exactly what CI does and doesn't cover.
- 193 tests green across 4 packages (generator 16, core 72 + 1 skipped,
  host 81, model 24).

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

All planned phases (A, B, C, D) are complete. There is no next phase
queued — the roadmap table above lists what's still deferred
(zone-level profitability's own remaining edges aside, mainly live
weather/sync boundary, remote sensing, a prescriptive crop model, and
absolute agronomy calibration), none of it scheduled. A future session
picking any of these back up should read this file in full first, then
follow the same discipline every phase here did: plan first, `ExitPlan
Mode` for approval, implement, verify, stop and report before scope
creeps into the next thing.
