# Precision Farm MCP v1 — Evaluation Questions

Ten independent, read-only questions for the CLI, in the style of the
precision-medicine-mcp evals: each requires at least one real MCP tool call
(several route through reconciliation across two independent sources), and
each has a single answer that's verifiable directly against
`data/synthetic/ground_truth.json` (seed 42). No question depends on the
answer to another.

Run any of them with:

```bash
uv run --project host farm-cli "<question>"
```

---

### 1. Chronic loss pattern
**Q:** Was the Marginal Eighty a bad field or just a bad year?
**Tool:** `report-export.bad_field_or_bad_year(field_name="Marginal Eighty")`
**Verifiable answer:** `verdict = "bad_field"`, loss in `10/10` recorded
seasons (`loss_rate = 1.0`). Ground truth: `marginal_field_id` field, every
season in `profitability.<field>.*.profit < 0`.

### 2. A genuine one-season outlier
**Q:** Was East 80 a bad field or just a bad year?
**Tool:** `report-export.bad_field_or_bad_year(field_name="East 80")`
**Verifiable answer:** `verdict = "bad_year"`, outlier season is exactly
`[2020]`, median profit/acre `$139.24`. Ground truth: `catastrophic_year`
= `{"field_id": "root_02", "season": 2020, "cause": "hail"}`.

### 3. A normal, unremarkable field
**Q:** Was West 120 a bad field or just a bad year?
**Tool:** `report-export.bad_field_or_bad_year(field_name="West 120")`
**Verifiable answer:** `verdict = "consistently_profitable"`, loss in only
`3/10` seasons, median profit/acre `$164.03`. Included as the negative
control: most fields in the record are neither pattern.

### 4. Ranking over a relative window
**Q:** Which fields made money in the last five years?
**Tool:** `report-export.which_fields_made_money(seasons=[2021..2025])`
**Verifiable answer:** Top result is **Section Corner**, total profit
`$169,720.44`; Marginal Eighty is last, total profit `-$87,773.68`. The
five-year window must resolve to `[2021, 2022, 2023, 2024, 2025]` — the
five most recent known seasons, not any other five.

### 5. Ranking over explicit named years
**Q:** Which fields made money in 2019 and 2020?
**Tool:** `report-export.which_fields_made_money(seasons=[2019, 2020])`
**Verifiable answer:** Top result is **Depot Forty**, total profit
`$44,527.24`. Named years must resolve to exactly `[2019, 2020]`, not a
relative-count guess.

### 6. Naming-drift resolution
**Q:** What does "north eighty" refer to in 2017?
**Tool:** `field-registry.resolve_field_name(raw_name="north eighty", season=2017)`
**Verifiable answer:** Resolves to canonical boundary name **"N 80"** via
`method = "alias"`. Ground truth: `DEF-NAMEDRIFT-root_04`, one of four
spelling variants ("N 80" / "north eighty" / "North 80" / "N80") cycling by
season.

### 7. A genuine yield-monitor discrepancy
**Q:** Do the yield monitor and scale tickets agree on Coulee Field in 2021?
**Tool:** `yield-history.get_yield_reconciliation(field_name="Coulee Field", season=2021)`
**Verifiable answer:** `totals_discrepancy = true`, `pct_diff ≈ -3.4%`
(monitor total 13,748 bu vs. scale ticket total 14,228 bu). Ground truth:
`DEF-CAL-2021-root_11`.

### 8. A coverage gap that totals alone would miss
**Q:** Is there anything odd about the yield monitor coverage on Marginal
Eighty in 2024?
**Tool:** `yield-history.get_yield_reconciliation(field_name="Marginal Eighty", season=2024)`
**Verifiable answer:** `coverage_gap_flagged = true` **and**
`totals_discrepancy = false` — the defining property of this defect
(`DEF-SWATH-2024-root_10`) is that a totals-only check would miss it
entirely; only the spatial coverage check catches it.

### 9. A ledger entry that doesn't match its own inputs
**Q:** Does the seed cost on Riverside in 2022 match what was actually applied?
**Tool:** `cost-ledger.get_cost_reconciliation(field_name="Riverside", season=2022)`
**Verifiable answer:** The `"seed"` line item is `outlier_flagged = true`,
ledger seed cost `$95.55/ac` vs. as-applied-derived cost `≈$60.04/ac` —
and it is the single largest-magnitude outlier in the whole cost
reconciliation table. Ground truth: `DEF-DIGIT-2022-root_06` (the ledger's
correct value was `$59.55`, transposed to `$95.55`; the as-applied-derived
estimate is independently computed from actual application rates and
prices, so it lands close to, not exactly on, the pre-transposition figure).

### 10. A field that no longer exists
**Q:** What does "Township Rd 12" refer to in 2021?
**Tool:** `field-registry.resolve_field_name(raw_name="Township Rd 12", season=2021)`
**Verifiable answer:** A structured refusal —
`{"code": "not_found"}` — never a guess. Ground truth:
`evt_rental_lost_root_09`, lease ended after season 2019; no boundary
exists for this field from 2020 onward.

---

## What these are testing collectively

- **1–3** exercise the classifier's two failure-mode-vs-normal-case split —
  chronic pattern, one-off outlier, and neither.
- **4–5** exercise the deterministic relative-vs-explicit season resolution
  from Phase 5 (the model extracts a count or explicit years; a plain
  Python function resolves either into concrete seasons — never the model's
  own arithmetic).
- **6, 10** exercise field-identity resolution at its two extremes: a name
  that resolves through drift, and a name that correctly resolves to
  nothing at all.
- **7–9** exercise all three reconciliation defects Phase 2 was built to
  catch, including the one (#8) specifically designed so a naive
  totals-only check would pass it silently.
