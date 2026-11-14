"""Turns a farm-host AnswerResult into the HTML panels the grower web app
shows. Pure functions with no Gradio import, so they can be tested without a
browser, a model, or the MCP servers.

Every string that comes from the records or the model is passed through
html.escape: field names, notes and the model's sentence are untrusted text
and must never become markup.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from html import escape

from farm_host.cli import AnswerResult
from farm_host.farms import Farm
from farm_host.followups import resolved_label

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
    ("units", "Every number keeps its own unit (mm, inches, lb, gallons)"),
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
    "asked_name": "Name you asked about",
    "total_precip_mm": "Rain (mm)",
    "farm_average_precip_mm": "Farm average rain (mm)",
    "pct_vs_farm_average": "Versus farm average",
    "num_seasons_compared": "Seasons compared",
    "precip_rank_driest": "Rank, driest first",
    "crop_water_need_mm": "Crop water need (mm)",
    "precip_short_of_need_mm": "Short of need (mm)",
    "heat_stress_days": "Days above heat threshold",
    "farm_average_heat_stress_days": "Farm average hot days",
    "heat_stress_threshold_c": "Heat threshold (°C)",
    "awc_in": "Soil water capacity (in)",
    "farm_min_awc_in": "Farm lowest (in)",
    "min_field_name": "Lowest field",
    "farm_max_awc_in": "Farm highest (in)",
    "max_field_name": "Highest field",
    "num_current_fields": "Current fields",
    "crop": "Crop",
    "logged": "As-applied log exists",
    "logged_seasons": "Seasons with logs",
    "applied_inputs": "Applied inputs",
    "input": "Input",
    "product": "Product",
    "rate": "Rate",
    "unit": "Unit",
    "as_logged_rate": "As logged",
    "as_logged_unit": "Logged unit",
    "converted": "Converted",
    "nitrogen_lb_n_ac": "Nitrogen (lb N/ac)",
    "uan32_lb_n_per_gal": "UAN 32% (lb N per gallon)",
    "nitrogen_by_season": "Nitrogen by season",
    "nitrogen_by_crop": "Nitrogen range by crop",
    "n_lb_n_ac": "Nitrogen (lb N/ac)",
    "min_lb_n_ac": "Lowest (lb N/ac)",
    "min_season": "Lowest in",
    "max_lb_n_ac": "Highest (lb N/ac)",
    "max_season": "Highest in",
    "spread_lb_n_ac": "Spread (lb N/ac)",
    "logs_start_season": "Logs start",
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
# Whole-number percentages computed by the tool itself (not 0-1 fractions).
_WHOLE_PERCENT_KEYS = {"pct_vs_farm_average"}
_YEAR_KEYS = {"season", "zone_index", "min_season", "max_season", "logs_start_season"}


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
        if key in _WHOLE_PERCENT_KEYS:
            return f"{value:+d}%"
        if key in _PERCENT_KEYS:
            return f"{value * 100:+.1f}%" if key == "pct_diff" else f"{value * 100:.0f}%"
        if key.endswith("_per_ac") or key.endswith("_per_acre") or (
            any(h in key for h in _MONEY_HINTS) and isinstance(value, float)
        ):
            sign = "-" if value < 0 else ""
            return f"{sign}${abs(value):,.2f}"
        if isinstance(value, float):
            return f"{value:,.2f}" if not key.endswith("_per_gal") else f"{value:g}"
        if key in _YEAR_KEYS:
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
        if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            continue  # a group of records (e.g. nitrogen by crop): its own table
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


def _resolved_html(result: AnswerResult) -> str:
    """Which question was actually answered -- most useful for a follow-up
    like "what about East 80?", where a wrong guess would otherwise look
    exactly like a right answer."""
    label = resolved_label(result)
    if not label:
        return ""
    return f'<p class="pf-resolved"><span>Showing:</span> {escape(label)}</p>'


def _answer_html(result: AnswerResult) -> str:
    n = result.narration
    resolved = _resolved_html(result)
    if not result.ok:
        title = {
            "model_unreachable": "The local AI model isn't running",
            "unparseable": "I couldn't match that to a question I can answer",
            "unresolved_followup": "I wasn't sure which field or season you meant",
            "tool_refused": "Your records don't have an answer to that",
            "server_timeout": "The lookup took too long to start",
            "error": "Something went wrong on this computer",
        }.get(result.refusal_kind or "", "No answer this time")
        return (
            '<div class="pf-answer pf-answer-refused">'
            f"{resolved}"
            f'<p class="pf-eyebrow">{escape(title)}</p>'
            f"<p>{escape(result.text)}</p>"
            '<p class="pf-muted">Saying "I don\'t know" is part of the design: '
            "this tool would rather refuse than guess.</p></div>"
        )
    if n is None:  # a caller that didn't come through the narrated path
        return f'<div class="pf-answer">{resolved}<p>{escape(result.text)}</p></div>'

    parts = [
        '<div class="pf-answer">',
        resolved,
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
    elif n.rejected_texts:
        # The sentence itself is never shown here: only that one was blocked.
        parts += [
            '<div class="pf-line pf-line-withheld">',
            '<span class="pf-tag pf-tag-withheld">AI sentence withheld</span>',
            "<p>The AI wrote a sentence, but it failed a check, so it isn't part of your "
            "answer. <em>How we checked it</em> shows what it wrote and why it was stopped.</p>",
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


def _check_list(failed: tuple[str, ...] | list[str]) -> str:
    """Every check in order, marked passed or failed; any failed check the
    labels don't know yet is listed too, never dropped."""
    failed = tuple(failed)
    items = [
        f'<li class="{"fail" if name in failed else "pass"}">'
        f'<span class="pf-mark" aria-hidden="true">{"&#10007;" if name in failed else "&#10003;"}'
        f"</span>{escape(label)}</li>"
        for name, label in CHECKS
    ]
    items += [
        f'<li class="fail"><span class="pf-mark" aria-hidden="true">&#10007;</span>'
        f"{escape(name)}</li>"
        for name in failed
        if name not in _CHECK_LABELS
    ]
    return '<ul class="pf-checks">' + "".join(items) + "</ul>"


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
        out.append(_check_list(()))
    elif n.rejected_texts:
        tries = len(n.rejected_texts)
        out.append(
            '<p class="pf-verdict pf-warn">The AI\'s sentence was withheld: it failed '
            + ("a check" if tries == 1 else f"a check on all {tries} tries")
            + ", so you only see the answer calculated from your records.</p>"
        )
    else:
        out.append(
            '<p class="pf-verdict pf-ok">The AI had nothing to add, so you see only the '
            "answer calculated from your records.</p>"
        )

    # When the sentence was withheld, every rejected attempt is open, with the
    # full checklist, so the failed check is visible without a click. When a
    # later try passed, the rejected ones stay folded away.
    withheld = n.context is None
    for i, (failed, text) in enumerate(zip(n.failed_checks, n.rejected_texts), start=1):
        out.append(
            f'<details class="pf-rejected"{" open" if withheld else ""}>'
            f"<summary>Try {i}: what the AI wrote, and why it was blocked</summary>"
            f"<blockquote>{escape(text)}</blockquote>{_check_list(failed)}"
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
        elif (
            isinstance(value, dict)
            and value
            and key not in ("modeled",)
            and all(isinstance(v, dict) for v in value.values())
        ):
            # {"corn": {...}, "soybean": {...}} -> one row per group.
            out.append(_table([{"crop": k, **v} for k, v in value.items()], caption=_label(key)))

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


def farm_badge_html(farm: Farm) -> str:
    return (
        f'<p class="pf-farm-badge pf-farm-{escape(farm.key)}">'
        f"<strong>{escape(farm.name)}</strong> \u00b7 {escape(farm.records)}</p>"
    )


def farm_note_html(farm: Farm) -> str:
    """The line under the farm picker."""
    return f'<p class="pf-farm-note">{escape(farm.blurb)}</p>'


def with_farm(view: AnswerView, farm: Farm) -> AnswerView:
    """Marks the answer with the farm whose records it came from, so an
    answer can never be mistaken for the other farm's."""
    html = view.answer_html
    if html.startswith("<div"):  # inside the answer card, above everything else
        end = html.index(">") + 1
        html = html[:end] + farm_badge_html(farm) + html[end:]
    else:
        html = farm_badge_html(farm) + html
    return dataclass_replace(view, answer_html=html)
