# Comparing models

Developers only. The grower web app always uses `gemma3:4b`, and nothing on
this page changes it. These commands run the same app code with another
small open model from Ollama, so you can see which parts depend on the model.

## The models

All three are small, open-weight models that run on a Mac with Ollama, at
similar sizes to Gemma.

| Model | Made by | Ollama tag | Parameters | Download | Pull it once |
|---|---|---|---|---|---|
| Gemma 3 (the default) | Google | `gemma3:4b` | 4.3B | about 3.3 GB | `ollama pull gemma3:4b` |
| Phi-4-mini | Microsoft | `phi4-mini` | 3.8B | about 2.5 GB | `ollama pull phi4-mini` |
| Granite 4 Micro | IBM | `granite4:micro` | 3B | about 2.1 GB | `ollama pull granite4:micro` |

The app does not use tool calling. The model fills in one JSON form (the
question type, field and seasons), and Ollama holds it to that form, so any
Ollama model can be tried. Inkling 2 Mini was looked at and left out: as of
November 2026 it doesn't run under Ollama (it needs Unsloth's own llama.cpp
build), and its 4-bit download is about 17.6 GB.

## What the model does, and what it doesn't

| Part of the answer | Who writes it | Changes with the model? |
|---|---|---|
| Which question type, field and seasons | The model | Yes: this is what the comparison tests most |
| The green answer and its figures | Code, from the records | No |
| The one blue AI sentence | The model, then 9 checks | Yes: it can be shown, withheld, or not written |
| The Therefore line | Code | No |

So a model can get a question wrong in only two ways: route it to the wrong
lookup (or the wrong field or season), or write a sentence the checks then
withhold. It can't change a figure.

## Grade the eval questions for each model

`farm-evals` asks the 15 [eval questions](EVAL_QUESTIONS.md), plus 4 of them
asked of Farm 1, with each model you name. It grades every answer against the
answer key in `host/src/farm_host/eval_key.py`, the same key the
`pytest -m eval_nl` suite uses. Ollama must be running.

```bash
uv run --project host farm-evals --models gemma3:4b phi4-mini granite4:micro
uv run --project host farm-evals --models phi4-mini --ids 2 9 farm1-eval7   # just these
```

It prints a summary and writes `data/model_comparison.md` (git-ignored;
`--out` to change it) with three parts:

| Part | What it shows |
|---|---|
| Summary | One row per model: questions passed, wrong route, wrong field or season, wrong answer, AI sentence shown or withheld, average seconds |
| By question | One row per question, one column per model: pass, or FAIL with the stage that failed |
| What failed | Each failure in one line: what the model did and what the key expected |

A model that isn't pulled is skipped and named in the summary. The command
exits 1 if any question failed, so it can be scripted. One model takes a
few minutes on a Mac; it is never run in CI.

## Results so far

First run on Lynn's Mac, 2026-11-22, all 19 questions per model. **Decision: Gemma 3 4B stays the default.**

| Model | Passed | Wrong answers shown | Failed on | AI sentence shown / withheld | Avg seconds |
|---|---|---|---|---|---|
| Gemma 3 4B (`gemma3:4b`) | 19 of 19 | 0 | nothing | 13 / 4 | 9.8 |
| Phi-4-mini (`phi4-mini`) | 14 of 19 | 0 | evals 6, 7, 10; Farm 1 evals 6, 7 | 12 / 1 | 6.1 |
| Granite 4 Micro (`granite4:micro`) | 17 of 19 | 0 | evals 10, 11 | 9 / 1 | 6.0 |

| What we learned | Why it matters |
|---|---|
| Every failure had the same cause: the right question type, but a required piece left out (the quoted name in "north eighty" or "Township Rd 12", the field Home Quarter, or the year 2024 for Section Corner) | The form check caught all 7 and refused the question. No model reached a lookup with the wrong field or season |
| No model showed a wrong figure | The figures and the Therefore line come from code. A weaker model means more "couldn't understand that" refusals, not wrong numbers. This is the teaching point for growers |
| Phi-4-mini struggles with quoted names | 4 of its 5 failures were "What does X refer to" questions or a name inside a longer question |
| Phi and Granite are about 40% faster | They're smaller, but the speed doesn't make up for the missed questions |
| Gemma writes more AI sentences, and more of them are withheld | Withheld sentences are the checks working, not failures |

To repeat the run, use the `farm-evals` command above. The results depend on the model build and the machine, so record the date with any new numbers.

## One question with another model

```bash
uv run --project host farm-cli --model phi4-mini "Was East 80 a bad field or just a bad year?"
uv run --project host python scripts/run_evals.py --model granite4:micro   # every eval, full answers
```

The audit log records the model on each question asked with `--model`.
