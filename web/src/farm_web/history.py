"""Question flow (formerly Session history): the audit log (data/audit.jsonl),
mapped as a flow (see flowmap.py) and read back one question at a time, so a
grower or a teacher can see what happened to every question: what was
looked up, which checks the blue AI sentence passed, and what was withheld. Read-only: the page never writes to the log.

A session is one run of the web app (every question it logs carries the same
`session_id`). Questions logged before session ids existed, and questions
from the terminal CLI, are grouped by time instead: a gap of more than
SESSION_GAP starts a new session.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import secrets
from html import escape
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from farm_core.audit import AuditLog
from farm_host.farms import FARMS
from farm_host.followups import TOPIC_LABELS
from farm_model.query_schema import QueryIntent

from .view import CHECKS

SESSION_GAP = datetime.timedelta(minutes=30)
HISTORY_PATH = "/history"

_CHECK_LABELS = dict(CHECKS)
_CHECK_SHORT = {
    "ungrounded": "Numbers",
    "verdict": "Verdict",
    "sign": "Gain/loss",
    "zone_premise": "Zones",
    "reconciliation": "Records agree",
    "attribution": "Modeled ≠ proven",
    "unsupported_cause": "No made-up cause",
    "units": "Units",
    "season_count": "Year count",
}
_SOURCE_LABELS = {"web": "Web app", "cli": "Terminal"}
_REFUSAL_TEXT = {
    "unresolved_followup": "not sure which field or season was meant",
    "season_not_named": "the question needs a season",
    "model_unreachable": "couldn't reach the local model",
    "out_of_scope": "not a question about your records",
    "out_of_range": "a season outside your records",
    "invalid_output": "the question couldn't be read",
    "not_found": "no field by that name in your records",
}


def new_session_id() -> str:
    """One per run of the web app: when it started, plus a few random
    characters so two runs started in the same second stay apart."""
    return f"web-{datetime.datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


@dataclasses.dataclass
class Question:
    entries: list[dict]

    @property
    def query(self) -> dict:
        return self.entries[0]

    def _first(self, event: str) -> dict | None:
        return next((e for e in self.entries if e["event"] == event), None)

    @property
    def text(self) -> str:
        return self.query.get("question", "")

    @property
    def started(self) -> datetime.datetime:
        return _when(self.query)

    @property
    def follow_up(self) -> bool:
        return bool(self.query.get("follow_up_context"))

    @property
    def source(self) -> str | None:
        return self.query.get("source")

    @property
    def farm(self) -> str | None:
        return self.query.get("farm")

    @property
    def session_id(self) -> str | None:
        return self.query.get("session_id")

    @property
    def parsed(self) -> dict | None:
        return self._first("parsed")

    @property
    def tool_call(self) -> dict | None:
        return self._first("tool_call")

    @property
    def narration(self) -> dict | None:
        return self._first("narration")

    @property
    def refusal(self) -> dict | None:
        return self._first("parse_refused") or self._first("tool_refused")

    @property
    def outcome(self) -> str:
        """shown | withheld | none (no AI sentence) | refused | listed | unfinished"""
        if self._first("capabilities_listed") is not None:
            return "listed"  # "What can I ask?": answered by code, nothing looked up
        if self.refusal is not None:
            return "refused"
        n = self.narration
        if n is None:
            return "unfinished"
        if "model_context_shown" in n:
            if n["model_context_shown"]:
                return "shown"
            return "withheld" if n.get("failed_checks") else "none"
        # Logged before model_context_shown existed.
        return "none" if n.get("used_fallback", True) else "shown"

    @property
    def failed_checks(self) -> list[str]:
        """Every check that blocked a sentence for this question, in order."""
        n = self.narration or {}
        return [c for attempt in n.get("failed_checks") or [] for c in attempt]

    @property
    def checks_recorded(self) -> bool:
        return "failed_checks" in (self.narration or {})

    @property
    def seconds(self) -> int | None:
        end = self.narration or self.refusal
        if end is None:
            return None
        return max(0, round((_when(end) - self.started).total_seconds()))


@dataclasses.dataclass
class Session:
    key: str
    questions: list[Question]
    labelled: bool  # True when the entries carry a session_id

    @property
    def started(self) -> datetime.datetime:
        return self.questions[0].started

    @property
    def ended(self) -> datetime.datetime:
        return self.questions[-1].started

    @property
    def source(self) -> str:
        sources = {q.source for q in self.questions if q.source}
        if len(sources) == 1:
            return _SOURCE_LABELS.get(next(iter(sources)), next(iter(sources)))
        return "Mixed" if sources else "Not recorded"

    @property
    def farms(self) -> list[str]:
        keys = sorted({q.farm for q in self.questions if q.farm})
        return [FARMS[k].name if k in FARMS else k for k in keys]

    def label(self) -> str:
        n = len(self.questions)
        parts = [f"{_date(self.started)}, {_time(self.started)}"]
        if self.labelled or any(q.source for q in self.questions):
            parts.append(self.source)
        if self.farms:
            parts.append(", ".join(self.farms))
        parts.append(f"{n} question{'s' if n != 1 else ''}")
        if not self.labelled:
            parts.append("grouped by time")
        return " · ".join(parts)


def questions_from(entries: list[dict]) -> list[Question]:
    """Each "query" entry starts a question; every entry up to the next one
    belongs to it (the app answers one question at a time)."""
    out: list[Question] = []
    for e in entries:
        if e.get("event") == "query":
            out.append(Question([e]))
        elif out:
            out[-1].entries.append(e)
    return out


def sessions_from(questions: list[Question]) -> list[Session]:
    """Oldest first. A question with a session_id joins that session; one
    without joins the previous unlabelled session unless SESSION_GAP passed."""
    sessions: list[Session] = []
    by_id: dict[str, Session] = {}
    last_unlabelled: Session | None = None
    for q in questions:
        if q.session_id:
            s = by_id.get(q.session_id)
            if s is None:
                s = by_id[q.session_id] = Session(q.session_id, [], labelled=True)
                sessions.append(s)
            s.questions.append(q)
            continue
        if last_unlabelled is None or q.started - last_unlabelled.ended > SESSION_GAP:
            key = f"{q.source or 'log'}-{q.started.astimezone(datetime.timezone.utc):%Y%m%dT%H%M%S}"
            last_unlabelled = Session(key, [], labelled=False)
            sessions.append(last_unlabelled)
        last_unlabelled.questions.append(q)
    sessions.sort(key=lambda s: s.started)
    return sessions


def _when(entry: dict) -> datetime.datetime:
    return datetime.datetime.fromisoformat(entry["timestamp"]).astimezone()


def _time(t: datetime.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _date(t: datetime.datetime) -> str:
    return f"{t:%b} {t.day}, {t.year}"


def _topic(intent: str | None) -> str:
    if not intent:
        return ""
    try:
        label = TOPIC_LABELS.get(QueryIntent(intent))
    except ValueError:
        label = None
    label = label or intent.replace("_", " ")
    return label[:1].upper() + label[1:]


# ---------------------------------------------------------------- rendering


def _entries_table(q: Question) -> str:
    rows = []
    for e in q.entries:
        detail = {
            k: v
            for k, v in e.items()
            if k not in ("event", "timestamp", "hash", "prev_hash")
        }
        rows.append(
            "<tr>"
            f"<td>{escape(_when(e).strftime('%H:%M:%S'))}</td>"
            f"<td><code>{escape(e['event'])}</code></td>"
            f"<td><code>{escape(json.dumps(detail, ensure_ascii=False, default=str))}</code></td>"
            f"<td><code>{escape(e.get('hash', '')[:10])}</code></td>"
            "</tr>"
        )
    return (
        f"<details><summary>The {len(q.entries)} log entries for this question</summary>"
        '<div class="tablewrap"><table><thead><tr><th>Time</th><th>Event</th><th>What it says</th>'
        f"<th>Hash</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>"
    )


def _question_html(q: Question) -> str:
    outcome = q.outcome
    css = {"shown": "shown", "withheld": "withheld"}.get(outcome, "other")
    tags = ""
    if q.follow_up:
        tags += '<span class="tag fu">follow-up</span>'
    if q.farm:
        tags += f'<span class="tag">{escape(FARMS[q.farm].name if q.farm in FARMS else q.farm)}</span>'

    meta = ""
    p, tc = q.parsed, q.tool_call
    if tc is not None:
        what = _topic(p.get("intent")) if p else tc.get("tool", "")
        bits = [f"Looked up <b>{escape(what)}</b>"]
        if p and p.get("field_name"):
            bits.append(f" for <b>{escape(str(p['field_name']))}</b>")
        if p and p.get("season"):
            bits.append(f", {escape(str(p['season']))}")
        tool = f"{tc.get('server', '')} → {tc.get('tool', '')}".strip(" →")
        meta = "".join(bits) + f" · <code>{escape(tool)}</code>"
        if q.seconds is not None:
            meta += f" · {q.seconds} s"

    n = q.narration or {}
    lead = (
        f'<p class="lead"><span class="who ver">Calculated by code</span> {escape(n["lead"])}</p>'
        if n.get("lead")
        else ""
    )
    body = ""
    if outcome == "shown":
        body = '<div class="outcome shown">✓ Blue AI sentence passed every check and was shown</div>'
        if n.get("shown_text"):
            body += (
                f'<p class="said"><span class="who model">Written by the AI</span> '
                f"{escape(n['shown_text'])}</p>"
            )
        else:
            body += '<p class="gap">The shown sentence wasn\'t saved in the log back then.</p>'
    elif outcome == "withheld":
        texts = n.get("rejected_texts") or []
        fails = q.failed_checks
        body = (
            f'<div class="outcome withheld">✕ Blue AI sentence withheld: it failed '
            f'{len(fails)} check{"s" if len(fails) != 1 else ""}</div>'
            + "".join(
                f'<div class="blocked">What the AI wrote: <s>{escape(t)}</s></div>' for t in texts
            )
            + '<p class="n">Blocked because: '
            + "; ".join(escape(_CHECK_LABELS.get(c, c)) for c in fails)
            + "</p>"
        )
    elif outcome == "none":
        body = '<div class="outcome other">The AI added no sentence (or couldn\'t be reached)</div>'
    elif outcome == "refused":
        r = q.refusal or {}
        why = r.get("kind") if r.get("event") == "parse_refused" else r.get("code")
        body = (
            '<div class="outcome other">⚠ Nothing looked up: '
            f"{escape(_REFUSAL_TEXT.get(why, str(why)))}</div>"
        )
    elif outcome == "listed":
        body = (
            '<div class="outcome other">Listed the kinds of questions it can answer '
            "(written by code: no AI, nothing looked up)</div>"
        )
    else:
        body = '<div class="outcome other">No answer was logged for this question</div>'

    checks = ""
    if outcome in ("shown", "withheld"):
        if q.checks_recorded:
            failed = set(q.failed_checks)
            chips = "".join(
                f'<span class="chk{" fail" if key in failed else ""}" title="{escape(label)}">'
                f'{"✕" if key in failed else "✓"} {escape(_CHECK_SHORT.get(key, key))}</span>'
                for key, label in CHECKS
            )
            checks = f'<div class="checks">{chips}</div>'
        else:
            checks = '<p class="gap">Which checks ran wasn\'t saved in the log back then.</p>'

    return f"""
<article class="q {css}" data-o="{css}" data-fu="{'1' if q.follow_up else '0'}">
  <header><div class="text">{escape(q.text)}{tags}</div>
    <div class="time">{_time(q.started)}</div></header>
  <div class="meta">{meta}</div>{lead}{body}{checks}
  {_entries_table(q)}
</article>"""


ALL_TIME = "all"


def _picker_html(sessions: list[Session], current_key: str, total: int) -> str:
    first = sessions[0].started
    options = [
        f'<option value="{ALL_TIME}"{" selected" if current_key == ALL_TIME else ""}>'
        f"All time · since {escape(_date(first))} · {total} questions</option>"
    ] + [
        f'<option value="{escape(s.key)}"{" selected" if s.key == current_key else ""}>'
        f"{escape(s.label())}</option>"
        for s in reversed(sessions)
    ]
    return (
        f'<form class="picker" method="get" action="{HISTORY_PATH}">'
        '<label for="pf-session">Show</label>'
        f'<select id="pf-session" name="session" onchange="this.form.submit()">{"".join(options)}</select>'
        '<noscript><button type="submit">Show</button></noscript></form>'
    )


def history_page(audit_log_path: Path, session_key: str | None = None) -> str:
    """The whole page, as one HTML document. Reads the log fresh each time."""
    log = AuditLog(audit_log_path)
    entries = log.entries()
    intact = log.verify()
    sessions = sessions_from(questions_from(entries))

    if intact:
        banner = (
            '<div class="intact ok"><b>Log intact.</b> All '
            f"{len(entries):,} entries checked: none edited, reordered or removed.</div>"
        )
    else:
        banner = (
            '<div class="intact bad"><b>Log changed.</b> The audit log no longer matches its '
            "own hashes: an entry was edited, reordered or removed after it was written.</div>"
        )

    if not sessions:
        main = '<p class="empty">No questions in the log yet. Ask one, then come back.</p>'
    else:
        from .flowmap import build_flow, flow_details_html, flow_legend_html, flow_svg

        current = next((s for s in sessions if s.key == session_key), None)
        key = current.key if current is not None else ALL_TIME
        questions = (
            current.questions if current is not None else [q for s in sessions for q in s.questions]
        )
        flow = build_flow(questions)
        filters = "".join(
            f'<button type="button" data-k="{k}" aria-pressed="{"true" if k == "all" else "false"}">'
            f"{label}</button>"
            for k, label in (
                ("all", "All"),
                ("shown", "AI sentence shown"),
                ("withheld", "Withheld"),
                ("other", "No AI sentence"),
                ("fu", "Follow-ups"),
            )
        )
        cards = "".join(_question_html(q) for q in reversed(questions))
        note = (
            '<p class="n">Grouped by time: these questions were logged before the web '
            "app saved a session, or came from the terminal.</p>"
            if current is not None and not current.labelled
            else ""
        )
        span = f"{_date(questions[0].started)}, {_time(questions[0].started)} to " + (
            f"{_date(questions[-1].started)}, {_time(questions[-1].started)}"
        )
        main = (
            _picker_html(sessions, key, sum(len(s.questions) for s in sessions))
            + note
            + '<section class="mapcard">'
            + f'<p class="n">{len(questions)} question{"s" if len(questions) != 1 else ""} · '
            + f"{escape(span)}</p>"
            + flow_svg(flow)
            + flow_legend_html()
            + f'<div class="nodeinfos">{flow_details_html(flow)}</div>'
            + "</section>"
            + '<details class="qlist"><summary>'
            + (f"The {len(questions)} questions, one by one" if len(questions) != 1 else "The question")
            + "</summary>"
            + f'<div class="filters" id="pf-filters">{filters}</div>'
            + f'<div id="pf-list">{cards}</div></details>'
        )

    return _PAGE.format(
        banner=banner,
        main=main,
        log_name=escape(f"{audit_log_path.parent.name}/{audit_log_path.name}"),
        home="/",
        css=_css(),
    )


def _css() -> str:
    return (files("farm_web") / "static" / "history.css").read_text(encoding="utf-8")


def history_link_html(text: str = "Question flow") -> str:
    return (
        f'<a class="pf-history-link" href="{quote(HISTORY_PATH)}" target="_blank" '
        f'rel="noopener">{escape(text)}</a>'
    )


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Question flow · Precision Farm</title>
<style>
{css}
</style>
</head>
<body>
<div class="wrap">
  <a href="{home}">← Back to questions</a>
  <h1>Question flow</h1>
  <p class="sub">Where questions went, read from the audit log
  (<code>{log_name}</code>). This page only reads the log; nothing here can be changed.</p>
  {banner}
  {main}
  <footer>Green text is calculated by code from your records. Blue text is written by the AI
  and is shown only when it passes every check.</footer>
</div>
<script>
(function () {{
  var infos = document.querySelectorAll(".nodeinfo");
  function pick(key) {{
    document.querySelectorAll(".flowmap .node").forEach(function (g) {{
      g.classList.toggle("picked", g.dataset.node === key);
    }});
    document.querySelectorAll(".flowmap .edge").forEach(function (e) {{
      e.classList.toggle("dim", !!key && e.dataset.from !== key && e.dataset.to !== key);
    }});
    infos.forEach(function (d) {{ d.hidden = d.dataset.info !== key; }});
  }}
  document.querySelectorAll(".flowmap .node").forEach(function (g) {{
    var go = function () {{ pick(g.classList.contains("picked") ? null : g.dataset.node); }};
    g.addEventListener("click", go);
    g.addEventListener("keydown", function (e) {{
      if (e.key === "Enter" || e.key === " ") {{ e.preventDefault(); go(); }}
    }});
  }});
  var bar = document.getElementById("pf-filters");
  if (!bar) return;
  bar.addEventListener("click", function (e) {{
    var k = e.target.getAttribute && e.target.getAttribute("data-k");
    if (!k) return;
    bar.querySelectorAll("button").forEach(function (b) {{
      b.setAttribute("aria-pressed", b === e.target ? "true" : "false");
    }});
    document.querySelectorAll("#pf-list .q").forEach(function (q) {{
      var show = k === "all" || (k === "fu" ? q.dataset.fu === "1" : q.dataset.o === k);
      q.style.display = show ? "" : "none";
    }});
  }});
}})();
</script>
</body>
</html>
"""
