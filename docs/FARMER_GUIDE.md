# Precision Farm MCP — A Guide for Farmers

This guide walks you through trying the tool out on your laptop: what it
is, how to install it, how to test it with example data first, and how to
eventually point it at your own farm's records.

No prior programming experience is assumed, but you will be typing
commands into a terminal window. If you get stuck, the [Troubleshooting](#troubleshooting)
section at the end covers the most common snags.

## What is this?

Precision Farm MCP answers plain-English questions about your own farm's
record — costs, yields, profit — by looking at your own files and doing
the arithmetic, never by guessing or predicting. For example:

> **You ask:** "Was the north eighty a bad field or just a bad year?"
> **It answers:** "The North Eighty had one clear outlier season over the
> past ten years — 2018 — well below its typical $62.81/acre median
> profit. Every other season was unremarkable, so this reads as a bad
> year, not a chronically bad field."

Everything happens on your own laptop. Your farm data is never sent
anywhere — not to a server, not to the internet, not anywhere outside your
machine. A small local AI model only ever does two things: turns your
question into a lookup, and turns the computed answer into a sentence. It
never touches your numbers directly and it never sees the internet — see
[README.md](../README.md) and [docs/ARCHITECTURE.md](ARCHITECTURE.md) for
how that's actually enforced and tested, if you're curious.

**This is v1, and it only answers questions about what already happened.**
It does not predict next year's yield, does not recommend what to plant,
and does not process satellite or drone imagery. Those are explicitly out
of scope for now — see the README for why.

## What you'll need

Three pieces of free software, installed once:

1. **The code itself** — either downloaded as a folder or checked out with
   `git clone` if you were given a repository link.
2. **`uv`** — the tool that installs and runs the Python programs in this
   project. One-time install, on a Mac terminal:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   (Windows and Linux installers are on [astral.sh/uv](https://astral.sh/uv).
   This tool is built to run on Windows too — the audit log's file locking,
   for instance, has explicit Windows and Mac/Linux code paths — but all of
   the actual day-to-day development and testing has happened on a Mac, so
   if you're on Windows, expect the exact commands below to differ
   slightly, mainly around how you install `uv` and open a terminal.)

3. **Ollama**, running a small local AI model — this is what turns your
   question into a lookup and the answer into a sentence. Download it from
   [ollama.com](https://ollama.com), install it like any other application,
   then pull the specific model this project uses:

   ```bash
   ollama pull gemma3:4b
   ```

   This downloads about 3-4 GB once. Ollama needs to be running in the
   background whenever you use `farm-cli` (it starts automatically after
   install on most systems).

That's the whole setup. Nothing else is downloaded, and once installed,
none of this needs an internet connection to actually answer a question.

## Step 1: Try it with example data first

The project comes with **ten seasons of realistic, entirely made-up farm
data** — a fictional North Dakota corn/soybean operation with the kind of
messiness real records have (misspelled field names, a field that got
split into two, a spreadsheet column that means something different in one
year than another). Trying this first lets you see how the tool behaves
before trusting it with your own numbers.

Open a terminal, navigate to the project folder, and run:

```bash
# Generate the ten seasons of example data (takes a few seconds)
uv run --project generator python -m farm_data_gen.cli --seed 42 --out data/synthetic
```

Next, run the one-time setup step. This is the only time the tool ever
asks you anything directly — it's confirming how to read the example
spreadsheet, once, so it never has to guess later:

```bash
uv run --project host farm-ingest
```

You'll see about a dozen prompts like:

```
[confirm] naming_drift_alias: Cost ledger name 'north eighty' in season 2017
  proposal: {'canonical_boundary_name': 'N 80'}
  confidence: high
  approve? [y/N]:
```

Read each one rather than reflexively typing `y` — **this example data
deliberately includes one prompt where the proposed match is wrong**, on
purpose, to prove the tool catches it rather than guessing:

```
[confirm] naming_drift_alias: Cost ledger name 'Hom Corner' in season 2023 has 2 acreage candidates, not exactly 1
  proposal: {'canonical_boundary_name': 'Section Corner'}
  confidence: low
```

That proposal is wrong — the ledger entry actually means "Home Quarter,"
not "Section Corner" (two unrelated fields happen to be the same size that
year, so acreage alone can't tell them apart, and the name similarity
happens to point the wrong way too). Type `N` and Enter to reject it, then
type `Home Quarter` when it asks for the correct name. For every other
prompt, `y` is correct. Notice the pattern for your own data too: a `low`
confidence is the tool's own signal to slow down and actually check,
rather than a formality.

Now ask it something:

```bash
uv run --project host farm-cli "was the north eighty a bad field or a bad year"
```

You should get back a real, grounded answer in a few seconds. The
[README](../README.md) has a short animated example of this in action, and
[docs/EVAL_QUESTIONS.md](EVAL_QUESTIONS.md) lists eleven more example
questions you can try, each with the verifiable correct answer written
out, so you can check the tool's answer against the known-right one — a
good way to build trust in it before moving to Step 2.

## Step 2: Load your own farm's data

**Read this section fully before starting — it currently expects your
records in a specific layout, matching the example data's shape exactly.**
This is a v1 prototype: there is not yet a friendly "drop in any
spreadsheet" importer, and reformatting your records into the expected
layout is the fiddliest part of using this tool today. If you have a
tech-savvy friend, agronomist, or ag-tech consultant, this is the step
where it's worth asking for a hand the first time.

The tool expects a folder (`data/synthetic/` by default — you can literally
replace what's in there) containing the pieces below. Column names need to
match **exactly** (spelling, capitalization, punctuation).

Two different things happen if a column doesn't match. Your cost ledger's
column headers go through the same confirm-once step as field names — the
tool proposes a mapping and a human checks it, same as Step 1. Everything
else (scale tickets, yield monitor, as-applied logs, weather, the Unit
Prices tab) is read directly by column name with no confirmation step: a
mismatch there fails loudly rather than silently misreading your data, but
today that failure is a technical error message (a database or Python
error), not yet a plain-language one. That's exactly why getting the
column names right matters, and why it's worth doing your first real load
next to someone who won't be thrown by an error message that looks
technical.

**Field boundaries** — `boundaries/field_boundaries_YYYY.geojson`, one file
per season. A standard GIS "GeoJSON" file (the format most farm-mapping
software can export to), one feature per field, each carrying these
properties: `field_name`, `acres`, `crop`, `season`.

**Your cost ledger** — `cost_ledger.xlsx`, a single spreadsheet. One tab
per season, the tab named just the year (`2024`, not "Season 2024"),
with these columns in this order:

`Field`, `Crop`, `Acres`, `Seed ($/ac)`, `Fertilizer ($/ac)`, `Chemical ($/ac)`, `Fuel ($/ac)`, `Cash Rent ($/ac)`, `Notes`

(If your ledger records total dollars for the field rather than a
per-acre rate, name the columns `Seed (Total $)` etc. instead — the tool
asks you at confirm time which basis a season uses, and remembers your
answer.)

Plus one shared tab, named exactly `Unit Prices`, one row per season, with
this exact header (this one has no confirmation step — it's read literally,
so the header must match precisely):

`Season`, `Seed Corn ($/unit)`, `Seed Soybean ($/unit)`, `N ($/lb)`, `P ($/lb)`, `K ($/lb)`, `Chemical ($/ac)`, `Fuel ($/gal)`

**Elevator/scale tickets** — `scale_tickets/scale_tickets_YYYY.csv`, one
file per season, one row per load, columns:

`season`, `ticket_number`, `date`, `field_name`, `crop`, `load_number`, `moisture_pct`, `gross_bushels`, `net_bushels`, `price_per_bu`, `elevator`

**Yield monitor data** — `yield_monitor/yield_monitor_<field>_YYYY.csv`,
one file per field per season (the field name and year live in the
filename itself, not as columns), one row per monitor reading:

`timestamp`, `lat`, `lon`, `wet_bu_ac`, `dry_bu_ac`, `moisture_pct`

**As-applied input logs** *(optional — only needed for recent seasons if
you want the sub-field "which part of this field is losing money"
questions to work)* — `as_applied/as_applied_YYYY.csv`, one row per
product application, columns:

`timestamp`, `field_name`, `product`, `rate`, `rate_unit`, `lat`, `lon`

**Weather** *(optional, only needed for "why was this a bad year — weather
or management" questions)* — `weather/weather_YYYY.csv` (`season`, `date`,
`precip_mm`, `temp_min_c`, `temp_max_c`) and one shared
`weather/soil_awc.csv` (`field_name`, `awc_in` — the soil's water-holding
capacity, in inches, a number your agronomist or soil survey can supply).

The example data already generated in Step 1 is a working, complete
example of every one of these — open the actual files under
`data/synthetic/` if a written-out column list is ever ambiguous. Field
names, seasons, and row counts can all differ from the example; file
naming and column names need to match what's listed above.

Once your files are in place:

```bash
# Confirm your own field names, column mappings, etc. -- once
uv run --project host farm-ingest

# Ask a real question about your own farm
uv run --project host farm-cli "which fields made money last year"
```

If you're adding a new season to data you've already confirmed once, only
the new parts will prompt you — `farm-ingest` remembers what it already
confirmed and only asks about what's changed.

**A tip for a clean start:** if you'd rather not mix your own confirmed
answers with the example data's, delete `data/confirmed_mappings.json` and
`data/audit.jsonl` before your first real `farm-ingest` run — they'll be
recreated automatically. Neither is required reading to use the tool; the
second one is just a running log of every decision the tool made, in case
you ever want to review it.

## Troubleshooting

- **"confirmation_required" refusal when asking a question** — you haven't
  run `farm-ingest` yet for this data, or you added new data since the last
  time you ran it. Run `farm-ingest` again.
- **The answer is a plain refusal, not a sentence** — this is by design,
  not a bug. The tool refuses rather than guesses whenever it isn't sure —
  an unrecognized field name, a season outside your records, or a question
  outside what v1 answers (predictions, recommendations). Rephrase, or
  check the field name and season you used are exactly as they appear in
  your data.
- **Ollama-related errors** — make sure Ollama is actually running
  (`ollama list` should show `gemma3:4b`) and that you ran `ollama pull
  gemma3:4b` at least once.
- **Something looks structurally wrong (a whole season missing, numbers
  that don't add up)** — check your file layout and column names against
  the working example in `data/synthetic/` first; a misnamed file or
  column is the most common cause.

## Where to go next

- [README.md](../README.md) — the technical overview, if you want more detail
  on how the tool is built and what makes it trustworthy.
- [docs/EVAL_QUESTIONS.md](EVAL_QUESTIONS.md) — eleven example questions
  with known-correct answers, good for building confidence in the tool.
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — the full technical design, for
  the curious or the technically inclined.
