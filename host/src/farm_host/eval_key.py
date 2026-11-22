"""The answer key for the 15 evaluation questions in docs/EVAL_QUESTIONS.md
(plus 4 asked of Farm 1's clean records): for each question, the intent,
server, tool and arguments it must route to, and the verified figures,
Therefore line or refusal code its answer must contain.

Used by two runners that ask the questions through the real path (a model
parses, the host routes to an MCP tool, the model may add one sentence):

- host/tests/test_eval_nl.py: pass/fail with gemma3:4b
  (`uv run --project host pytest -m eval_nl host/tests`).
- farm-evals (host/src/farm_host/evals_cli.py): the same questions for one
  or more Ollama models, side by side (see docs/MODELS.md).

grade() never asks a model anything: it reads the answer and its audit
entries only.
"""

from __future__ import annotations

import dataclasses

@dataclasses.dataclass(frozen=True)
class Eval:
    number: int
    question: str
    intent: str
    server: str
    tool: str
    args: dict
    contains: tuple[str, ...] = ()  # verified figures that must appear in the answer
    therefore: str | None = None  # expected Therefore line (substring); None = no line
    refusal_code: str | None = None  # expected structured refusal instead of an answer
    farm: str = "farm2"  # the web app's Farm 2 (messy records) is data/synthetic

    @property
    def id(self) -> str:
        return f"eval{self.number}" if self.farm == "farm2" else f"{self.farm}-eval{self.number}"


EVALS = [
    Eval(1, "Was the Marginal Eighty a bad field or just a bad year?",
         "bad_field_or_bad_year", "report-export", "bad_field_or_bad_year",
         {"field_name": "Marginal Eighty"},
         contains=("bad field, not a bad year", "10 of its 10"),
         therefore="lost money in 100% of its 10 recorded seasons"),
    Eval(2, "Was East 80 a bad field or just a bad year?",
         "bad_field_or_bad_year", "report-export", "bad_field_or_bad_year",
         {"field_name": "East 80"},
         contains=("bad year, not a bad field", "2020", "$68.19/ac"),
         therefore="the loss was isolated to 2020"),
    Eval(3, "Was South 160 South a bad field or just a bad year?",
         "bad_field_or_bad_year", "report-export", "bad_field_or_bad_year",
         {"field_name": "South 160 South"},
         contains=("1 of 6 recorded seasons", "$175.41/ac"),
         therefore="5 of its 6 recorded seasons had no loss"),
    Eval(4, "Which fields made money in the last five years?",
         "which_fields_made_money", "report-export", "which_fields_made_money",
         {"seasons": [2021, 2022, 2023, 2024, 2025]},
         contains=("East 80 ($135,533.57)",),
         therefore="12 of 13 fields made money over 2021-2025; East 80 ranked highest "
         "($135,533.57), Marginal Eighty lowest (-$112,044.66)"),
    Eval(5, "Which fields made money in 2019 and 2020?",
         "which_fields_made_money", "report-export", "which_fields_made_money",
         {"seasons": [2019, 2020]},
         contains=("Depot Forty ($17,551.40)",),
         therefore="3 of 14 fields made money over 2019-2020; Depot Forty ranked highest "
         "($17,551.40)"),
    Eval(6, 'What does "north eighty" refer to in 2017?',
         "resolve_field_name", "field-registry", "resolve_field_name",
         {"raw_name": "north eighty", "season": 2017},
         contains=("N 80",)),
    Eval(7, "Do the yield monitor and scale tickets agree on Home Quarter in 2019?",
         "yield_reconciliation", "yield-history", "get_yield_reconciliation",
         {"field_name": "Home Quarter", "season": 2019},
         contains=("5,008.2 bu", "4,683.5 bu", "do not agree")),
    Eval(8, "Is there anything odd about the yield monitor coverage on Marginal Eighty in 2024?",
         "yield_reconciliation", "yield-history", "get_yield_reconciliation",
         {"field_name": "Marginal Eighty", "season": 2024},
         contains=("17,513.6 bu", "17,430.5 bu", "agree within tolerance", "coverage has a gap")),
    Eval(9, "Does the seed cost on Sheyenne Bottom in 2022 look right?",
         "cost_reconciliation", "cost-ledger", "get_cost_reconciliation",
         {"field_name": "Sheyenne Bottom", "season": 2022},
         contains=("doesn't look right", "$95.55/ac", "$60.04/ac")),
    Eval(10, 'What does "Township Rd 12" refer to in 2020?',
         "resolve_field_name", "field-registry", "resolve_field_name",
         {"raw_name": "Township Rd 12", "season": 2020},
         refusal_code="not_found"),
    Eval(11, "Is any part of Section Corner losing money in 2024, even though the field "
         "overall is profitable?",
         "zone_profitability", "report-export", "zone_profitability",
         {"field_name": "Section Corner", "season": 2024},
         contains=("$5,897.56", "zone 0 (-$11,943.49)"),
         therefore="1 of 4 measurable zones lost money"),
    Eval(12, "How dry was 2018?",
         "season_weather", "weather-history", "get_season_weather",
         {"season": 2018},
         contains=("172.6 mm", "60% below the 10-season farm average of 434.4 mm",
                   "driest of the 10 seasons", "277.4 mm short of the 450 mm")),
    Eval(13, "How much water does Coulee Field's soil hold?",
         "field_soil", "weather-history", "get_field_soil",
         {"field_name": "Coulee Field"},
         contains=("6.93 inches", "4.08 in (West 120)")),
    Eval(14, "What did I put on Coulee Field in 2023?",
         "applied_inputs", "as-applied", "get_applied_inputs",
         {"field_name": "Coulee Field", "season": 2023},
         contains=("nitrogen at 145.9 lb N/ac", "logged as 41.22 gal/ac of UAN 32%")),
    Eval(15, "Did I put the same nitrogen on Section Corner every year?",
         "nitrogen_history", "as-applied", "get_nitrogen_history",
         {"field_name": "Section Corner"},
         contains=("2023 corn 160.6", "from 141.3 (2025) to 160.6 (2023)",
                   "no as-applied log before 2022")),
]


# The same questions asked of Farm 1 (same fields, clean records): the
# answer key is identical, but every record agrees, so the record checks
# pass where Farm 2's catch a problem -- the comparison growers see when
# they switch farms in the web app.
FARM1_EVALS = [
    Eval(2, "Was East 80 a bad field or just a bad year?",
         "bad_field_or_bad_year", "report-export", "bad_field_or_bad_year",
         {"field_name": "East 80"},
         contains=("bad year, not a bad field", "2020", "$68.19/ac"),
         therefore="the loss was isolated to 2020", farm="farm1"),
    # Farm 1's ledger never misspells N 80, so there is nothing to resolve.
    Eval(6, 'What does "north eighty" refer to in 2017?',
         "resolve_field_name", "field-registry", "resolve_field_name",
         {"raw_name": "north eighty", "season": 2017},
         refusal_code="not_found", farm="farm1"),
    Eval(7, "Do the yield monitor and scale tickets agree on Home Quarter in 2019?",
         "yield_reconciliation", "yield-history", "get_yield_reconciliation",
         {"field_name": "Home Quarter", "season": 2019},
         contains=("4,696.1 bu", "4,683.5 bu", "agree within tolerance"), farm="farm1"),
    Eval(9, "Does the seed cost on Sheyenne Bottom in 2022 look right?",
         "cost_reconciliation", "cost-ledger", "get_cost_reconciliation",
         {"field_name": "Sheyenne Bottom", "season": 2022},
         contains=("is in line with its as-applied records",), farm="farm1"),
]


def _norm(value):
    return value.strip().lower() if isinstance(value, str) else value


@dataclasses.dataclass
class Grade:
    """What went wrong, by stage. All three empty means the question passed.
    `route` covers the parsed intent and the server/tool it went to, `args`
    the tool's field/season arguments, `answer` the figures, Therefore line
    or refusal code."""

    route: list[str] = dataclasses.field(default_factory=list)
    args: list[str] = dataclasses.field(default_factory=list)
    answer: list[str] = dataclasses.field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.route or self.args or self.answer)

    def problems(self) -> list[str]:
        return self.route + self.args + self.answer


def grade(ev: Eval, result, events: list[dict]) -> Grade:
    """Grade one answer (a farm_host.cli.AnswerResult) and its audit entries
    against the key. A misroute stops there: the args and answer of the
    wrong tool say nothing more."""
    g = Grade()
    by_event = {e["event"]: e for e in events}

    if "parse_refused" in by_event:
        g.route.append(f"parse refused: {by_event['parse_refused']}")
        return g
    parsed = by_event.get("parsed", {}).get("intent")
    if parsed != ev.intent:
        g.route.append(f"intent {parsed!r}, expected {ev.intent!r}")
    call = by_event.get("tool_call")
    if call is None:
        g.route.append("no tool call")
        return g
    if (call["server"], call["tool"]) != (ev.server, ev.tool):
        g.route.append(f"routed to {call['server']}.{call['tool']}, expected {ev.server}.{ev.tool}")
    if g.route:
        return g

    for key, expected in ev.args.items():
        got = call["args"].get(key)
        if _norm(got) != _norm(expected):
            g.args.append(f"{key}={got!r}, expected {expected!r}")

    if ev.refusal_code:
        code = by_event.get("tool_refused", {}).get("code")
        if result.ok or code != ev.refusal_code:
            g.answer.append(f"expected refusal {ev.refusal_code!r}, got {code!r}")
        return g
    if not result.ok:
        g.answer.append(f"refused ({result.refusal_kind}): {result.text[:120]}")
        return g
    for figure in ev.contains:
        if figure not in result.text:
            g.answer.append(f"missing {figure!r}")
    if ev.therefore:
        if "Therefore: " not in result.text or ev.therefore not in result.text:
            g.answer.append(f"Therefore line missing {ev.therefore!r}")
    elif "Therefore:" in result.text:
        g.answer.append("unexpected Therefore line")
    return g
