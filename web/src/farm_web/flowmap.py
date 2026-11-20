"""The map on the Question flow page: every question in the
chosen time window, drawn as one picture of where questions went, like a
service map. Each circle is a step a question passes through (the question
reader, one of the six MCP servers, the AI sentence writer, the 9 checks)
or where it ended up; each arrow is how many questions took that path.

The ring around a circle shows how many passed through cleanly (green for
code, blue for the AI) and how many were refused or blocked there (amber or
red). Times are averages, measured between the step's own log entries.

Drawn as plain SVG by the app itself: no graph library, works offline.
"""

from __future__ import annotations

import dataclasses
import math
import statistics
from collections import Counter, defaultdict
from html import escape

from farm_host.cli import _INTENT_TO_SERVER, _INTENT_TO_TOOL

from .history import _CHECK_LABELS, _REFUSAL_TEXT, Question, _topic, _when
from .view import CHECKS

# The six MCP servers, in the order they're drawn (top to bottom).
SERVERS = (
    "report-export",
    "field-registry",
    "yield-history",
    "cost-ledger",
    "weather-history",
    "as-applied",
)
_SERVER_LABELS = {
    "report-export": "Field reports",
    "field-registry": "Field names",
    "yield-history": "Yield records",
    "cost-ledger": "Cost ledger",
    "weather-history": "Weather and soil",
    "as-applied": "What was applied",
}
# Which server answers each tool. Today's routing table, plus tools that
# early log entries (before tool_call carried a server) called directly.
_TOOL_SERVER = {
    _INTENT_TO_TOOL[intent]: server for intent, server in _INTENT_TO_SERVER.items()
} | {
    "get_as_applied_events": "as-applied",
    "list_yield_reconciliation": "yield-history",
    "resolve_field_identity": "field-registry",
    "get_cost_ledger_row": "cost-ledger",
}


@dataclasses.dataclass
class Node:
    key: str
    title: str
    kind: str  # "code" | "ai" | "end-ok" | "end-warn" | "end-bad"
    x: float
    y: float
    count: int = 0
    trouble: int = 0  # refused or blocked here
    seconds: list[float] = dataclasses.field(default_factory=list)
    details: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    @property
    def avg(self) -> float | None:
        return statistics.mean(self.seconds) if self.seconds else None


@dataclasses.dataclass
class Flow:
    nodes: dict[str, Node]
    edges: Counter  # (from, to) -> questions
    questions: int


def _secs(a: dict, b: dict) -> float:
    return max(0.0, (_when(b) - _when(a)).total_seconds())


def build_flow(questions: list[Question]) -> Flow:
    col = {"ask": 60, "reader": 200, "server": 430, "writer": 640, "checks": 790, "end": 935}
    nodes: dict[str, Node] = {
        "ask": Node("ask", "Questions asked", "code", col["ask"], 320),
        "reader": Node("reader", "Question reader (AI)", "ai", col["reader"], 320),
        "writer": Node("writer", "AI sentence writer", "ai", col["writer"], 320),
        "checks": Node("checks", "9 checks", "code", col["checks"], 260),
        "shown": Node("shown", "Shown", "end-ok", col["end"], 140),
        "withheld": Node("withheld", "Withheld", "end-bad", col["end"], 300),
        "none": Node("none", "No AI sentence", "end-warn", col["end"], 470),
        "refused": Node("refused", "Not looked up", "end-warn", 290, 610),
    }
    for i, s in enumerate(SERVERS):
        nodes[s] = Node(s, _SERVER_LABELS[s], "code", col["server"], 45 + i * 110)

    edges: Counter = Counter()
    sources: Counter = Counter()
    refusals: Counter = Counter()
    tools: dict[str, Counter] = defaultdict(Counter)
    tool_refusals: dict[str, Counter] = defaultdict(Counter)
    intents: Counter = Counter()
    blocked: Counter = Counter()

    for q in questions:
        ask = nodes["ask"]
        ask.count += 1
        sources[{"web": "Web app", "cli": "Terminal"}.get(q.source or "", "Not recorded")] += 1
        parsed, refusal, tc, n = q.parsed, q.refusal, q.tool_call, q.narration

        reader = nodes["reader"]
        if parsed is None and refusal is not None and refusal.get("event") == "parse_refused":
            reader.count += 1
            reader.trouble += 1
            reader.seconds.append(_secs(q.query, refusal))
            refusals[refusal.get("kind")] += 1
            edges[("ask", "reader")] += 1
            edges[("reader", "refused")] += 1
            nodes["refused"].count += 1
            continue
        if tc is None:
            continue  # unfinished, or an old entry with no lookup logged
        reader.count += 1
        edges[("ask", "reader")] += 1
        if parsed is not None:
            reader.seconds.append(_secs(q.query, parsed))
            intents[_topic(parsed.get("intent"))] += 1

        server = tc.get("server") or _TOOL_SERVER.get(tc.get("tool", ""))
        if server not in nodes:
            continue
        s = nodes[server]
        s.count += 1
        tools[server][tc.get("tool", "?")] += 1
        if parsed is not None:
            s.seconds.append(_secs(parsed, tc))
        edges[("reader", server)] += 1

        if q.outcome == "refused":  # the server refused (e.g. no such field)
            s.trouble += 1
            tool_refusals[server][(refusal or {}).get("code")] += 1
            edges[(server, "refused")] += 1
            nodes["refused"].count += 1
            continue
        if n is None:
            continue

        writer = nodes["writer"]
        writer.count += 1
        writer.seconds.append(_secs(tc, n))
        edges[(server, "writer")] += 1
        outcome = q.outcome
        if outcome == "none":
            edges[("writer", "none")] += 1
            nodes["none"].count += 1
            continue
        checks = nodes["checks"]
        checks.count += 1
        edges[("writer", "checks")] += 1
        for c in q.failed_checks:
            blocked[c] += 1
        if outcome == "withheld":
            checks.trouble += 1
            edges[("checks", "withheld")] += 1
            nodes["withheld"].count += 1
        else:
            edges[("checks", "shown")] += 1
            nodes["shown"].count += 1

    # What a click on each circle shows.
    nodes["ask"].details = [(k, str(v)) for k, v in sources.most_common()]
    nodes["reader"].details = [("Understood", str(nodes["reader"].count - nodes["reader"].trouble))] + [
        (f"Refused: {_REFUSAL_TEXT.get(k, k)}", str(v)) for k, v in refusals.most_common()
    ] + [("Question type: " + k, str(v)) for k, v in intents.most_common()]
    for s in SERVERS:
        nodes[s].details = [(f"<code>{escape(t)}</code>", str(v)) for t, v in tools[s].most_common()] + [
            (f"Refused: {_REFUSAL_TEXT.get(k, k)}", str(v)) for k, v in tool_refusals[s].most_common()
        ]
    nodes["writer"].details = [
        ("Wrote a sentence", str(nodes["checks"].count)),
        ("Added nothing (or couldn't be reached)", str(nodes["none"].count)),
    ]
    nodes["checks"].details = [
        (escape(label), f"blocked {blocked[key]}" if blocked[key] else "passed every time")
        for key, label in CHECKS
    ]
    nodes["shown"].details = [("The grower read the blue AI sentence", str(nodes["shown"].count))]
    nodes["withheld"].details = [
        (escape(_CHECK_LABELS.get(k, k)), str(v)) for k, v in blocked.most_common()
    ]
    nodes["none"].details = [("Only the green answer, calculated by code", str(nodes["none"].count))]
    nodes["refused"].details = [
        (f"By the question reader: {_REFUSAL_TEXT.get(k, k)}", str(v)) for k, v in refusals.most_common()
    ] + [
        (f"By {_SERVER_LABELS[s]}: {_REFUSAL_TEXT.get(k, k)}", str(v))
        for s in SERVERS
        for k, v in tool_refusals[s].most_common()
    ]
    return Flow(nodes, edges, len(questions))


# ---------------------------------------------------------------- drawing

R = 30  # circle radius


def _arc(cx: float, cy: float, r: float, start: float, frac: float) -> str:
    """An SVG arc path from `start` (fraction of a turn, 0 = top) covering `frac`."""
    if frac >= 0.999:
        return (
            f"M {cx} {cy - r} A {r} {r} 0 1 1 {cx - 0.01} {cy - r}"
        )
    a0 = 2 * math.pi * start - math.pi / 2
    a1 = 2 * math.pi * (start + frac) - math.pi / 2
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if frac > 0.5 else 0
    return f"M {x0:.1f} {y0:.1f} A {r} {r} 0 {large} 1 {x1:.1f} {y1:.1f}"


def _node_svg(n: Node) -> str:
    ok_color = {"code": "var(--ver)", "ai": "var(--model)", "end-ok": "var(--model)",
                "end-bad": "var(--loss)", "end-warn": "var(--warn)"}[n.kind]
    idle = n.count == 0
    ring = ""
    if idle:
        ring = f'<circle cx="{n.x}" cy="{n.y}" r="{R}" class="ring idle"/>'
    elif n.kind.startswith("end"):
        ring = f'<circle cx="{n.x}" cy="{n.y}" r="{R}" class="ring" style="stroke:{ok_color}"/>'
    else:
        bad = n.trouble / n.count
        bad_color = "var(--loss)" if n.key == "checks" else "var(--warn)"
        ring = f'<path d="{_arc(n.x, n.y, R, 0, 1 - bad)}" class="ring" style="stroke:{ok_color}"/>'
        if bad > 0:
            ring += (
                f'<path d="{_arc(n.x, n.y, R, 1 - bad, bad)}" class="ring" '
                f'style="stroke:{bad_color}"/>'
            )
    sub = []
    if n.avg is not None:
        sub.append(f"{n.avg:.1f} s avg" if n.avg >= 0.1 else "&lt;0.1 s avg")
    if n.trouble:
        word = "blocked" if n.key == "checks" else "refused"
        sub.append(f"{n.trouble} {word}")
    sub_text = " · ".join(sub)
    return f"""
<g class="node{' idle' if idle else ''}" data-node="{n.key}" tabindex="0" role="button"
   aria-label="{escape(n.title)}: {n.count}">
  <circle cx="{n.x}" cy="{n.y}" r="{R}" class="disc"/>{ring}
  <text x="{n.x}" y="{n.y + 6}" class="count">{n.count}</text>
  <text x="{n.x}" y="{n.y + R + 18}" class="title">{escape(n.title)}</text>
  <text x="{n.x}" y="{n.y + R + 34}" class="sub">{sub_text}</text>
</g>"""


def _edge_svg(a: Node, b: Node, count: int, biggest: int, tone: str) -> str:
    width = 1.5 + 9 * math.sqrt(count / biggest)
    # Leave each circle at its edge, curving gently between columns.
    dx, dy = b.x - a.x, b.y - a.y
    dist = math.hypot(dx, dy) or 1
    x0, y0 = a.x + dx / dist * (R + 4), a.y + dy / dist * (R + 4)
    x1, y1 = b.x - dx / dist * (R + 10), b.y - dy / dist * (R + 10)
    if abs(y1 - y0) > 2 * abs(x1 - x0):  # mostly up or down: bend vertically
        my = (y0 + y1) / 2
        path = f"M {x0:.1f} {y0:.1f} C {x0:.1f} {my:.1f}, {x1:.1f} {my:.1f}, {x1:.1f} {y1:.1f}"
    else:
        mx = (x0 + x1) / 2
        path = f"M {x0:.1f} {y0:.1f} C {mx:.1f} {y0:.1f}, {mx:.1f} {y1:.1f}, {x1:.1f} {y1:.1f}"
    # The count sits 40% along, clear of the busy area around each circle.
    lx, ly = x0 + (x1 - x0) * 0.4, y0 + (y1 - y0) * 0.4
    return (
        f'<path d="{path}" class="edge {tone}" style="stroke-width:{width:.1f}" '
        f'marker-end="url(#arrow-{tone})" data-from="{a.key}" data-to="{b.key}"/>'
        f'<g class="elabel"><rect x="{lx - 14}" y="{ly - 9}" width="28" height="18" rx="9"/>'
        f'<text x="{lx}" y="{ly + 4}">{count}</text></g>'
    )


def flow_svg(flow: Flow) -> str:
    biggest = max(flow.edges.values(), default=1)
    edges = []
    for (a, b), count in sorted(flow.edges.items(), key=lambda kv: -kv[1]):
        tone = "bad" if b == "withheld" else "warn" if b in ("refused", "none") else "ok"
        edges.append(_edge_svg(flow.nodes[a], flow.nodes[b], count, biggest, tone))
    markers = "".join(
        f'<marker id="arrow-{t}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="11" '
        f'markerHeight="11" markerUnits="userSpaceOnUse" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" class="ah {t}"/></marker>'
        for t in ("ok", "warn", "bad")
    )
    nodes = "".join(_node_svg(n) for n in flow.nodes.values())
    return (
        '<svg class="flowmap" viewBox="0 0 1000 680" role="img" '
        f'aria-label="Map of where {flow.questions} questions went">'
        f"<defs>{markers}</defs>{''.join(edges)}{nodes}</svg>"
    )


def flow_details_html(flow: Flow) -> str:
    """One hidden panel per circle; clicking the circle shows it."""
    out = []
    for n in flow.nodes.values():
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in n.details) or (
            '<tr><td colspan="2">Nothing went through here in this time window.</td></tr>'
        )
        avg = f" · {n.avg:.1f} s on average" if n.avg is not None and n.avg >= 0.1 else ""
        out.append(
            f'<div class="nodeinfo" data-info="{n.key}" hidden><h3>{escape(n.title)}</h3>'
            f'<p class="n">{n.count} question{"s" if n.count != 1 else ""}{avg}</p>'
            f"<table>{rows}</table></div>"
        )
    return "".join(out)


def flow_legend_html() -> str:
    return (
        '<div class="maplegend">'
        '<span><i class="sw" style="background:var(--ver)"></i>code (green)</span>'
        '<span><i class="sw" style="background:var(--model)"></i>AI (blue)</span>'
        '<span><i class="sw" style="background:var(--warn)"></i>refused / nothing added</span>'
        '<span><i class="sw" style="background:var(--loss)"></i>blocked by a check</span>'
        "<span>Arrow width = number of questions. Click a circle for details.</span></div>"
    )
