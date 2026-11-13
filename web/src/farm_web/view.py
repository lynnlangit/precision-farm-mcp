"""Turns a farm-host AnswerResult into the HTML panels the grower web app
shows. Pure functions with no Gradio import, so they can be tested without a
browser, a model, or the MCP servers.

Every string that comes from the records or the model is passed through
html.escape: field names, notes and the model's sentence are untrusted text
and must never become markup.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from farm_host.cli import AnswerResult

# The checks a model-written sentence must pass before a grower sees it, in
# the order the narrator runs them. Labels are plain language on purpose:
# this panel is the AI-literacy lesson.
CHECKS: tuple[tuple[str, str], ...] = (
    ("ungrounded", "Every number in it appears in your records"),
    ("verdict", "It agrees with the verified answer"),
    ("sign", "Gains are gains and losses are losses"),
    ("zone_premise", "It describes the right zones"),
    ("reconciliation", "It says correctly whether two records agree"),
    ("attribution", "It doesn't treat a modeled estimate as a proven cause"),
    ("unsupported_cause", "It doesn't name a cause your records don't show"),
)
_CHECK_LABELS = dict(CHECKS)

# Keys that are bookkeeping for the software, not figures a grower needs.
_HIDDEN_KEYS = {"canonical_id", "provenance", "modeled", "unavailable_reason"}

_LABELS = {
    "verdict": "Verdict",
    "field_name": "Field",
    "display_name": "Field",
    "season": "Season",
    "seasons": "Seasons",
    "outlier_seasons": "Outlier seasons",
    "median_profit_per_acre": "Median profit per acre",
    "num_seasons": "Seasons on record",
    "num_loss_seasons": "Seasons with a loss",
    "loss_rate": "Share of seasons with a loss",
    "total_profit": "Total profit",
    "total_revenue": "Total revenue",
    "total_cost": "Total cost",
    "field_acres": "Field acres",
    "field_profit": "Field profit",
    "zone_index": "Zone",
    "acres": "Acres",
    "available": "Data available",
    "point_count": "Yield points",
    "yield_bu_ac": "Yield (bu/ac)",
    "revenue": "Revenue",
    "cost": "Cost",
    "profit": "Profit",
    "scale_total_bu": "Scale tickets (bu)",
    "monitor_total_bu": "Yield monitor (bu)",
    "pct_diff": "Difference",
    "totals_discrepancy": "Totals disagree",
    "coverage_gap_bins": "Coverage gap bins",
    "coverage_gap_flagged": "Coverage gap found",
    "line_item": "Line item",
    "ledger_cost_per_ac": "Ledger ($/ac)",
    "as_applied_derived_cost_per_ac": "From as-applied ($/ac)",
    "outlier_flagged": "Flagged",
    "canonical_boundary_name": "Field it refers to",
    "method": "How it was matched",
    "note": "Note",
    "season_effect": "Weather effect",
    "field_effect": "Field effect",
    "residual": "Unexplained",
}

_VERDICTS = {
    "bad_field": "Bad field (a repeating pattern)",
    "bad_year": "Bad year (a one-season outlier)",
    "consistently_profitable": "Consistently profitable",
    "no_data": "Not enough data",
}

_REPEATED_CONTEXT_KEYS = {"field_name", "season", "available", "calibrated"}

_MONEY_HINTS = ("profit", "revenue", "cost")
_PERCENT_KEYS = {"pct_diff", "loss_rate"}


def _label(key: str) -> str:
    return _LABELS.get(key, key.replace("_", " ").capitalize())


def format_value(key: str, value: object) -> str:
    """One cell's display text, already HTML-escaped."""
    if value is None:
        return "&mdash;"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if key == "verdict" and isinstance(value, str):
        return escape(_VERDICTS.get(value, value))
    if isinstance(value, (int, float)):
        if key in _PERCENT_KEYS:
            return f"{value * 100:+.1f}%" if key == "pct_diff" else f"{value * 100:.0f}%"
        if key.endswith("_per_ac") or key.endswith("_per_acre") or (
            any(h in key for h in _MONEY_HINTS) and isinstance(value, float)
        ):
            sign = "-" if value < 0 else ""
            return f"{sign}${abs(value):,.2f}"
        if isinstance(value, float):
            return f"{value:,.2f}"
        if key in ("season", "zone_index"):
            return str(value)
        return f"{value:,}"
    if isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
        return escape(", ".join(str(v) for v in value)) or "&mdash;"
    return escape(str(value))


def _cell_class(key: str, value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cls = "num"
        if value < 0 and (any(h in key for h in _MONEY_HINTS) or key in ("residual",)):
            cls += " neg"
        return cls
    if isinstance(value, bool) and value and key in (
        "totals_discrepancy",
        "coverage_gap_flagged",
        "outlier_flagged",
    ):
        return "flag"
    return ""


def _is_scalarish(v: object) -> bool:
    if isinstance(v, list):
        return all(not isinstance(x, (dict, list)) for x in v)
    return not isinstance(v, dict)


def _scalar_rows(payload: dict) -> list[tuple[str, object]]:
    rows: list[tuple[str, object]] = []
    for key, value in payload.items():
        if key in _HIDDEN_KEYS or key == "note":
            continue
        if isinstance(value, dict):
            rows.extend(
                (k, v) for k, v in value.items() if k not in _HIDDEN_KEYS and _is_scalarish(v)
            )
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            continue  # shown as its own table
        else:
            rows.append((key, value))
    return rows


_FLAG_KEYS = ("totals_discrepancy", "coverage_gap_flagged", "outlier_flagged")


def _is_flagged(record: dict) -> bool:
    return any(record.get(k) is True for k in _FLAG_KEYS)


def _table(records: list[dict], caption: str | None = None) -> str:
    keys: list[str] = []
    for rec in records:
        for k, v in rec.items():
            if k in _HIDDEN_KEYS or k in keys or isinstance(v, dict) or k == "meaning":
                continue
            keys.append(k)
    # Drop columns that are empty in every row, long notes (shown below the
    # table instead), and context columns that repeat one value in every row.
    keys = [
        k
        for k in keys
        if k != "note"
        and any(rec.get(k) not in (None, "", []) for rec in records)
        and not (
            k in _REPEATED_CONTEXT_KEYS
            and len(records) > 1
            and len({str(rec.get(k)) for rec in records}) == 1
        )
    ]
    head = "".join(f"<th>{escape(_label(k))}</th>" for k in keys)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{_cell_class(k, rec.get(k))}">{format_value(k, rec.get(k))}</td>'
            for k in keys
        )
        + "</tr>"
        for rec in records
    )
    cap = f"<caption>{escape(caption)}</caption>" if caption else ""
    notes = "".join(
        f'<p class="pf-note{"" if _is_flagged(rec) else " pf-note-ok"}">'
        f'{escape(str(rec["note"]))}</p>'
        for rec in records
        if rec.get("note")
    )
    return (
        f'<div class="pf-table-wrap"><table class="pf-table">{cap}<thead><tr>{head}</tr>'
        f"</thead><tbody>{body}</tbody></table></div>{notes}"
    )


@dataclass(frozen=True)
class AnswerView:
    answer_html: str
    checks_html: str
    figures_html: str
    source_html: str


_EMPTY_CHECKS = (
    '<p class="pf-muted">After you ask, this shows every check the AI\'s sentence had to pass '
    "before you were allowed to see it.</p>"
)
_EMPTY_FIGURES = (
    '<p class="pf-muted">The exact figures from your records that the answer is built on.</p>'
)
_EMPTY_SOURCE = '<p class="pf-muted">Which records were read, and which tool read them.</p>'


def empty_view() -> AnswerView:
    return AnswerView(
        answer_html=(
            '<div class="pf-answer pf-answer-empty">'
            '<p class="pf-eyebrow">Your answer</p>'
            "<p>Ask about one of your fields, or tap an example question. "
            "Answers come only from your own records.</p></div>"
        ),
        checks_html=_EMPTY_CHECKS,
        figures_html=_EMPTY_FIGURES,
        source_html=_EMPTY_SOURCE,
    )


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _answer_html(result: AnswerResult) -> str:
    n = result.narration
    if not result.ok:
        title = {
            "model_unreachable": "The local AI model isn't running",
            "unparseable": "I couldn't match that to a question I can answer",
            "tool_refused": "Your records don't have an answer to that",
            "server_timeout": "The lookup took too long to start",
            "error": "Something went wrong on this computer",
        }.get(result.refusal_kind or "", "No answer this time")
        return (
            '<div class="pf-answer pf-answer-refused">'
            f'<p class="pf-eyebrow">{escape(title)}</p>'
            f"<p>{escape(result.text)}</p>"
            '<p class="pf-muted">Saying "I don\'t know" is part of the design: '
            "this tool would rather refuse than guess.</p></div>"
        )
    if n is None:  # a caller that didn't come through the narrated path
        return f'<div class="pf-answer"><p>{escape(result.text)}</p></div>'

    parts = [
        '<div class="pf-answer">',
        '<p class="pf-eyebrow">Your answer</p>',
        '<div class="pf-line pf-line-verified">',
        '<span class="pf-tag pf-tag-verified">Calculated from your records</span>',
        f'<p class="pf-lead">{escape(n.lead)}</p>',
        "</div>",
    ]
    if n.context:
        parts += [
            '<div class="pf-line pf-line-model">',
            '<span class="pf-tag pf-tag-model">Added by the AI, then checked</span>',
            f"<p>{escape(n.context)}</p>",
            "</div>",
        ]
    if result.therefore:
        parts += [
            '<div class="pf-line pf-line-therefore">',
            '<span class="pf-tag pf-tag-verified">What that means</span>',
            f"<p>{escape(_sentence_case(result.therefore.removeprefix('Therefore: ')))}</p>",
            "</div>",
        ]
    parts.append("</div>")
    return "".join(parts)


def _checks_html(result: AnswerResult) -> str:
    n = result.narration
    if not result.ok or n is None:
        return (
            '<p class="pf-muted">No AI sentence was written, so there was nothing to check. '
            "The question was stopped before any numbers were looked up or described.</p>"
            if result.refusal_kind != "tool_refused"
            else '<p class="pf-muted">The lookup ran, but your records had no answer, '
            "so nothing was written for the AI to check.</p>"
        )

    out: list[str] = []
    if n.context:
        out.append(
            '<p class="pf-verdict pf-ok">The AI\'s sentence passed all '
            f"{len(CHECKS)} checks"
            + (f" on try {len(n.rejected_texts) + 1}" if n.rejected_texts else "")
            + ", so it's shown.</p>"
        )
        out.append('<ul class="pf-checks">')
        out += [
            f'<li class="pass"><span class="pf-mark" aria-hidden="true">&#10003;</span>'
            f"{escape(label)}</li>"
            for _, label in CHECKS
        ]
        out.append("</ul>")
    elif n.rejected_texts:
        out.append(
            '<p class="pf-verdict pf-warn">The AI tried to add a sentence, but it failed a '
            "check, so you only see the answer calculated from your records.</p>"
        )
    else:
        out.append(
            '<p class="pf-verdict pf-ok">The AI had nothing to add, so you see only the '
            "answer calculated from your records.</p>"
        )

    for i, (failed, text) in enumerate(zip(n.failed_checks, n.rejected_texts), start=1):
        failed_labels = "".join(
            f'<li class="fail"><span class="pf-mark" aria-hidden="true">&#10007;</span>'
            f"{escape(_CHECK_LABELS.get(name, name))}</li>"
            for name in failed
        )
        out.append(
            '<details class="pf-rejected">'
            f"<summary>Rejected attempt {i}: what the AI wrote, and why it was blocked</summary>"
            f'<blockquote>{escape(text)}</blockquote><ul class="pf-checks">{failed_labels}</ul>'
            "</details>"
        )
    return "".join(out)


def _figures_html(result: AnswerResult) -> str:
    payload = result.payload
    if not payload:
        return '<p class="pf-muted">No figures were looked up for this question.</p>'
    if "error" in payload:
        return f'<p class="pf-muted">{escape(str(payload.get("error")))}</p>'

    out: list[str] = []
    rows = _scalar_rows(payload)
    if rows:
        out.append('<dl class="pf-figures">')
        out += [
            f"<div><dt>{escape(_label(k))}</dt>"
            f'<dd class="{_cell_class(k, v)}">{format_value(k, v)}</dd></div>'
            for k, v in rows
        ]
        out.append("</dl>")
    if payload.get("note"):
        cls = "pf-note" if _is_flagged(payload) else "pf-note pf-note-ok"
        out.append(f'<p class="{cls}">{escape(str(payload["note"]))}</p>')
    for key, value in payload.items():
        if key in _HIDDEN_KEYS:
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            out.append(_table(value, caption=_label(key) if key != "results" else None))

    modeled = payload.get("modeled") or {}
    attribution = modeled.get("attribution") if isinstance(modeled, dict) else None
    if attribution:
        units = attribution[0].get("units", "")
        out.append(
            '<div class="pf-modeled"><p class="pf-eyebrow">Modeled estimate, not a measurement</p>'
            "<p>A simple statistical model splits the yield shortfall into weather, the field "
            f"itself, and what's left unexplained. Units: {escape(units)}.</p>"
            + _table([{k: v for k, v in row.items() if k != "units"} for row in attribution])
            + "</div>"
        )
    return "".join(out)


def _source_html(result: AnswerResult) -> str:
    rows: list[tuple[str, str]] = []
    if result.query is not None:
        rows.append(("Question type", escape(result.query.intent.value.replace("_", " "))))
    if result.server and result.tool:
        rows.append(("Looked up by", f"<code>{escape(result.server)}</code> &rarr; "
                                     f"<code>{escape(result.tool)}</code>"))
    if result.tool_args:
        args = ", ".join(f"{k} = {v}" for k, v in result.tool_args.items())
        rows.append(("With", escape(args)))
    prov = (result.payload or {}).get("provenance") or {}
    if prov.get("source_file_count") is not None:
        rows.append(("Records read", f"{prov['source_file_count']:,} of your files"))
    if prov.get("built_at"):
        built = escape(str(prov["built_at"])[:19].replace("T", " "))
        rows.append(("Snapshot built", f"{built} UTC"))
    if not rows:
        return _EMPTY_SOURCE
    body = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows)
    return (
        f'<dl class="pf-figures pf-source">{body}</dl>'
        '<p class="pf-muted">Nothing left this computer. Every question is also written to '
        "<code>data/audit.jsonl</code>.</p>"
    )


def build_view(result: AnswerResult) -> AnswerView:
    return AnswerView(
        answer_html=_answer_html(result),
        checks_html=_checks_html(result),
        figures_html=_figures_html(result),
        source_html=_source_html(result),
    )
