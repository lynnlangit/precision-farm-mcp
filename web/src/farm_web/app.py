"""Local web app for grower testing: a thin Gradio layer over farm-host.

    uv run --project web farm-web            # http://127.0.0.1:7860 on this laptop
    uv run --project web farm-web --lan      # also reachable on the shared Wi-Fi

Every question goes through farm_host.cli.answer_question, the same path the
CLI and the eval suite use, so the browser can never show an answer the
terminal wouldn't. Read-only, and every question is written to the audit log.
"""

from __future__ import annotations

import os

# Before gradio is imported: no usage analytics leave this machine.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import argparse  # noqa: E402
import dataclasses  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from html import escape  # noqa: E402
from importlib.resources import files  # noqa: E402
from pathlib import Path  # noqa: E402

import gradio as gr  # noqa: E402

from farm_core.audit import AuditLog  # noqa: E402
from farm_host.cli import DEFAULT_AUDIT_LOG, AnswerResult, answer_question  # noqa: E402
from farm_host.farms import DEFAULT_FARM, FARMS, Farm  # noqa: E402
from farm_host.followups import MAX_SUGGESTIONS, next_context, suggest_followups  # noqa: E402
from farm_host.server_pool import ServerPool  # noqa: E402
from farm_host.mcp_client import ServerStartTimeout  # noqa: E402
from farm_host.preflight_cli import (  # noqa: E402
    check_confirmed_mappings,
    check_model_pulled,
    check_ollama_running,
    check_synthetic_data,
)

from . import __version__  # noqa: E402
from .banner import BANNER_HTML  # noqa: E402
from farm_model.query_schema import FollowUpContext  # noqa: E402

from .view import (  # noqa: E402
    AnswerView,
    build_view,
    empty_view,
    farm_note_html,
    with_farm,
)

# The eval questions (docs/EVAL_QUESTIONS.md), grouped the way a grower thinks.
EXAMPLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Bad field or bad year?",
        (
            "Was East 80 a bad field or just a bad year?",
            "Was the Marginal Eighty a bad field or just a bad year?",
            "Was South 160 South a bad field or just a bad year?",
        ),
    ),
    (
        "Which fields made money?",
        (
            "Which fields made money in the last five years?",
            "Which fields made money in 2019 and 2020?",
            "Is any part of Section Corner losing money in 2024, even though the field "
            "overall is profitable?",
        ),
    ),
    (
        "Do my records agree?",
        (
            "Do the yield monitor and scale tickets agree on Home Quarter in 2019?",
            "Is there anything odd about the yield monitor coverage on Marginal Eighty in 2024?",
            "Does the seed cost on Sheyenne Bottom in 2022 look right?",
            'What does "north eighty" refer to in 2017?',
        ),
    ),
    (
        "Weather and soil",
        (
            "How dry was 2018?",
            "How much water does Coulee Field's soil hold?",
        ),
    ),
    (
        "What did I apply?",
        (
            "What did I put on Coulee Field in 2023?",
            "Did I put the same nitrogen on Section Corner every year?",
        ),
    ),
    (
        # Eval 2 again, filed where a grower looking for it will find it: with
        # gemma3:4b the AI's sentence blames "an unusual weather pattern",
        # which no record shows, so it fails the "doesn't name a cause" check
        # and is withheld (host/tests/test_eval_nl.py -k withheld).
        "When the AI is stopped",
        ("Was East 80 a bad field or just a bad year?",),
    ),
)


def status_html() -> str:
    """The quick preflight checks (no server start, no model call), as chips."""
    ollama_check, pulled = check_ollama_running()
    checks = [ollama_check, check_model_pulled(pulled)]
    for farm in FARMS.values():
        checks += _farm_checks(farm)
    chips = "".join(
        f'<span class="pf-chip {"ok" if c.ok else "bad"}" title="{escape(c.detail)}">'
        f"{escape(c.name)}</span>"
        for c in checks
    )
    fixes = [c for c in checks if not c.ok and c.fix]
    fix_list = (
        '<ul class="pf-fixes">'
        + "".join(f"<li><strong>{escape(c.name)}:</strong> {escape(c.fix)}</li>" for c in fixes)
        + "</ul>"
        if fixes
        else ""
    )
    # Collapsed to one line at the bottom of the page when everything is
    # ready; at the top, open, when something needs fixing, so a problem is
    # never hidden.
    failing = sum(1 for c in checks if not c.ok)
    if failing:
        summary = f"{failing} of {len(checks)} need attention"
        cls, open_attr = "bad", " open"
    else:
        summary = f"{len(checks)} of {len(checks)}"
        cls, open_attr = "ok", ""
    return (
        f'<details class="pf-status-wrap"{open_attr}>'
        f'<summary><span class="pf-status-label">Prerequisites loaded</span>'
        f'<span class="pf-chip {cls}">{summary}</span></summary>'
        f'<div class="pf-status">{chips}</div>{fix_list}</details>'
    )


def _farm_checks(farm: Farm) -> list:
    """The data checks, once per farm, named and fixed for that farm."""
    data = check_synthetic_data(farm.data_dir)
    mappings = check_confirmed_mappings(farm.confirm_store)
    return [
        dataclasses.replace(
            data, name=f"{farm.name} data generated", fix=None if data.ok else f"run `{farm.generate_cmd}`"
        ),
        dataclasses.replace(
            mappings,
            name=f"{farm.name} farm-ingest has run",
            fix=None if mappings.ok else f"run `{farm.ingest_cmd}`",
        ),
    ]


def status_panels() -> tuple[str, str]:
    """(top, bottom): the prerequisites go at the top only when one fails."""
    html = status_html()
    return (html, "") if " open>" in html else ("", html)


def _panels(view: AnswerView) -> tuple[str, str, str, str]:
    return view.answer_html, view.checks_html, view.figures_html, view.source_html


def _followup_updates(suggestions: list[str]) -> list:
    """One update for the heading, then one per suggestion button slot."""
    heading = gr.update(visible=bool(suggestions))
    buttons = [
        gr.update(value=suggestions[i], visible=True)
        if i < len(suggestions)
        else gr.update(value="", visible=False)
        for i in range(MAX_SUGGESTIONS)
    ]
    return [heading, *buttons]


def _context_dump(context: FollowUpContext | None) -> dict | None:
    return context.model_dump(mode="json") if context is not None else None


class FarmPools:
    """One ServerPool per farm, each started the first time it's needed.

    Farm 1's servers start when the app opens; Farm 2's start when someone
    first picks it (about 7 s, once), so a session that never switches
    farms never pays for the second set."""

    def __init__(self, audit_log_path: Path, factory=None):
        audit_env = {"FARM_AUDIT_LOG": str(audit_log_path.resolve())}
        self._factory = factory or (
            lambda farm: ServerPool(env_overrides={**audit_env, **farm.server_env()})
        )
        self._pools: dict[str, object] = {}
        self._lock = threading.Lock()

    def get(self, farm_key: str):
        with self._lock:
            if farm_key not in self._pools:
                self._pools[farm_key] = self._factory(FARMS[farm_key])
            return self._pools[farm_key]

    def warm(self, farm_key: str) -> None:
        """Start that farm's servers in the background, if not started yet."""
        pool = self.get(farm_key)
        if hasattr(pool, "start_in_background"):  # a no-op once its servers are up
            pool.start_in_background()


def _farm_key(value: str | None) -> str:
    return value if value in FARMS else DEFAULT_FARM


def context_for(
    question: str | None, context_state: dict | None, last_ask: dict | None
) -> dict | None:
    """The follow-up context a question is asked with.

    Pressing "Ask my records" again on the question that is already
    answered asks it again exactly as before -- with the context that
    question was first asked with, not as a follow-up to its own answer.
    Without this, the second press sent the parser a different prompt (the
    question plus "the last answer was about East 80 ..."), so the same
    words could come back as a different answer."""
    q = (question or "").strip()
    if last_ask and q and q == last_ask.get("question"):
        return last_ask.get("context")
    return context_state


class SessionTickets:
    """A counter per browser tab, bumped by Clear.

    An answer still being looked up when Clear is pressed can't be stopped
    (Gradio lets a running function finish), so it checks its ticket when it
    comes back and is dropped if Clear was pressed meanwhile -- otherwise it
    would land on a page the grower just cleared, with an empty box."""

    def __init__(self):
        self._tickets: dict[str, int] = {}
        self._lock = threading.Lock()

    def current(self, session: str) -> int:
        with self._lock:
            return self._tickets.get(session, 0)

    def bump(self, session: str) -> None:
        with self._lock:
            self._tickets[session] = self._tickets.get(session, 0) + 1


class BusyTabs:
    """Which browser tabs have a question being answered right now.

    Every way of asking first claims its tab here, on the server; a second
    claim while the first question is still being answered is refused, so
    Enter followed by a quick click (two different events, which Gradio
    doesn't stop on its own) sends the question once, not twice. A claim
    older than STALE_AFTER seconds is ignored, so a tab can never stay
    locked for good."""

    STALE_AFTER = 600.0

    def __init__(self):
        self._since: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, session: str) -> bool:
        now = time.monotonic()
        with self._lock:
            since = self._since.get(session)
            if since is not None and now - since < self.STALE_AFTER:
                return False
            self._since[session] = now
            return True

    def release(self, session: str) -> None:
        with self._lock:
            self._since.pop(session, None)


ASK_LABEL = "Ask my records"
LOCK_NOW_JS = """() => {
  document.querySelectorAll('#pf-ask, #pf-question textarea').forEach((el) => {
    el.disabled = true;
  });
  return [];
}"""
BUSY_LABEL = "Looking it up..."


def make_ask(audit_log_path: Path, pools: FarmPools | None = None):
    """The handler for one question. Gradio state holds only the follow-up
    context (field, season, question type) and the picked farm -- never the
    answers themselves.

    `pools` keeps each farm's MCP servers running between questions (see
    farm_host.server_pool); without one, one is created here."""
    audit_log = AuditLog(audit_log_path)
    pools = pools or FarmPools(audit_log_path)

    def ask(question: str, context_state: dict | None = None, farm_key: str | None = None) -> tuple:
        farm = FARMS[_farm_key(farm_key)]
        pool = pools.get(farm.key)
        server_env = {"FARM_AUDIT_LOG": str(audit_log_path.resolve()), **farm.server_env()}
        context = FollowUpContext.model_validate(context_state) if context_state else None
        question = (question or "").strip()
        if not question:
            return (
                *_panels(empty_view()),
                _context_dump(context),
                *_followup_updates([]),
            )
        try:
            # Runs on the pool's event loop, against servers that are already
            # running; the answer path itself is the CLI's answer_question.
            result = pool.run(
                lambda fleet: answer_question(
                    question, audit_log, env_overrides=server_env, context=context, fleet=fleet
                )
            )
        except ServerStartTimeout as e:
            result = AnswerResult(text=str(e), ok=False, refusal_kind="server_timeout")
        except Exception as e:  # noqa: BLE001 -- show a grower a sentence, not a traceback
            result = AnswerResult(
                text=(
                    "Something went wrong on this computer while looking that up. "
                    f"Run `uv run --project host farm-preflight` to check the setup. ({e})"
                ),
                ok=False,
                refusal_kind="error",
            )
        new_context = next_context(result, context)
        return (
            *_panels(with_farm(build_view(result), farm)),
            _context_dump(new_context),
            *_followup_updates(suggest_followups(result)),
        )

    return ask


def build_app(
    audit_log_path: Path = DEFAULT_AUDIT_LOG, pools: FarmPools | None = None
) -> gr.Blocks:
    pools = pools or FarmPools(audit_log_path)
    ask = make_ask(audit_log_path, pools)
    empty = empty_view()

    with gr.Blocks(title="Precision Farm", analytics_enabled=False) as app:
        gr.HTML(BANNER_HTML)
        top_status, bottom_html = status_panels()
        status_top = gr.HTML(top_status)

        with gr.Row(equal_height=False):
            with gr.Column(scale=5, min_width=320):
                gr.HTML('<p class="pf-h">Whose records?</p>')
                farm_picker = gr.Radio(
                    choices=[(f.label, f.key) for f in FARMS.values()],
                    value=DEFAULT_FARM,
                    show_label=False,
                    container=False,
                    elem_classes="pf-farm-picker",
                )
                farm_note = gr.HTML(farm_note_html(FARMS[DEFAULT_FARM]))
                gr.HTML('<p class="pf-h" style="margin-top:14px">Ask a question</p>'
                        '<p class="pf-h-sub">About one of the fields and seasons.</p>')
                # One line that grows to four: Enter asks, Shift+Enter starts a
                # new line. (With lines=2, Gradio made Enter a new line and
                # Shift+Enter send -- the opposite of every chat box.)
                question = gr.Textbox(
                    show_label=False,
                    placeholder="e.g. Was East 80 a bad field or just a bad year?",
                    lines=1,
                    max_lines=4,
                    autofocus=True,
                    elem_id="pf-question",
                )
                with gr.Row():
                    ask_btn = gr.Button(
                        ASK_LABEL, variant="primary", scale=3, elem_id="pf-ask"
                    )
                    clear_btn = gr.Button("Clear", variant="secondary", scale=1, elem_id="pf-clear")
                example_buttons: list[tuple[gr.Button, str]] = []
                gr.HTML('<p class="pf-eyebrow" style="margin-top:14px">Example questions</p>')
                for heading, qs in EXAMPLES:
                    with gr.Accordion(
                        f"{heading} ({len(qs)})", open=False, elem_classes="pf-example-group"
                    ):
                        with gr.Column(elem_classes="pf-examples-group"):
                            for q in qs:
                                b = gr.Button(q, size="sm", elem_classes="pf-example")
                                example_buttons.append((b, q))
            with gr.Column(scale=7, min_width=340):
                answer = gr.HTML(empty.answer_html, elem_id="pf-answer")
                followup_heading = gr.HTML(
                    '<p class="pf-eyebrow" style="margin-top:12px">Ask next</p>'
                    '<p class="pf-muted">Each one is a full question, looked up and checked '
                    "from scratch. Questions that leave out the field or year use the ones "
                    "shown above; press Clear to start over.</p>",
                    visible=False,
                )
                with gr.Column(elem_classes="pf-followups-group"):
                    followup_buttons = [
                        gr.Button("", size="sm", elem_classes="pf-example", visible=False)
                        for _ in range(MAX_SUGGESTIONS)
                    ]

        with gr.Row(equal_height=False):
            with gr.Column(scale=4, min_width=300, elem_classes="pf-panel"):
                gr.HTML('<p class="pf-h">How we checked it</p>'
                        "<p class=\"pf-h-sub\">The AI's sentence is shown only if it passes "
                        "every one of these.</p>")
                checks = gr.HTML(empty.checks_html, elem_id="pf-checks")
            with gr.Column(scale=6, min_width=320, elem_classes="pf-panel"):
                gr.HTML('<p class="pf-h">The numbers behind it</p>'
                        '<p class="pf-h-sub">Straight from your records, no AI involved.</p>')
                figures = gr.HTML(empty.figures_html)
                gr.HTML('<p class="pf-h" style="margin-top:12px">Where it came from</p>')
                source = gr.HTML(empty.source_html)

        # Follow-up context: the last verified answer's field, season and
        # question type. Per browser tab; Clear resets it.
        context_state = gr.State(None)
        # The question last sent and the context it was sent with, so asking
        # the same question again repeats it exactly (see context_for).
        last_ask = gr.State(None)
        panels = [answer, checks, figures, source]
        outputs = [*panels, context_state, followup_heading, *followup_buttons, last_ask]
        inputs = [question, context_state, farm_picker, last_ask]
        tickets = SessionTickets()

        def ask_in_tab(q, ctx, farm_key, last, request: gr.Request):
            session = request.session_hash or ""
            ticket = tickets.current(session)
            used = context_for(q, ctx, last)
            result = ask(q, used, farm_key)
            if tickets.current(session) != ticket:  # Clear was pressed meanwhile
                return [gr.skip()] * len(outputs)
            asked = (q or "").strip()
            new_last = {"question": asked, "context": used} if asked else None
            return [*result, new_last]

        # While a question is being answered, the box and every control
        # that would ask another question are locked, and the button says
        # so. Before this, a second click was silently dropped (Gradio ignores a click while
        # that button's last one is still running), and an example or a new
        # question typed meanwhile left the box showing one question and the
        # answer panel another.
        ask_controls = [
            ask_btn,
            question,
            farm_picker,
            *(b for b, _ in example_buttons),
            *followup_buttons,
        ]

        def lock():
            return [gr.update(value=BUSY_LABEL, interactive=False)] + [
                gr.update(interactive=False) for _ in ask_controls[1:]
            ]

        def unlock():
            return [gr.update(value=ASK_LABEL, interactive=True)] + [
                gr.update(interactive=True) for _ in ask_controls[1:]
            ]

        ask_events = []
        busy = BusyTabs()

        def claim(request: gr.Request):
            # Raising stops the rest of this event's chain; invisible, because
            # the grower already sees "Looking it up..." for the first one.
            if not busy.claim(request.session_hash or ""):
                raise gr.Error("Already answering a question", visible=False,
                               print_exception=False)

        def release(request: gr.Request):
            busy.release(request.session_hash or "")
            return unlock()

        def ask_chain(trigger, fill=None, fill_inputs=None, fill_outputs=None, js=None):
            """claim -> (put the question in the box) -> lock -> ask -> unlock."""
            event = trigger(claim, queue=False, js=js)
            if fill is not None:
                event = event.success(fill, inputs=fill_inputs, outputs=fill_outputs, queue=False)
            asked = event.success(lock, outputs=ask_controls, queue=False).success(
                ask_in_tab, inputs=inputs, outputs=outputs
            )
            ask_events.append(asked)
            asked.then(release, outputs=ask_controls, queue=False)

        # The two ways a typed question is sent, exactly once each: the
        # button, and Enter in the box. Typing, clicking away or pasting
        # sends nothing. LOCK_NOW_JS greys both out in the browser at once,
        # before the server's lock arrives.
        ask_chain(ask_btn.click, js=LOCK_NOW_JS)
        ask_chain(question.submit, js=LOCK_NOW_JS)

        def switch_farm(farm_key: str, current_question: str):
            # Start the other farm's servers now, and drop the follow-up
            # context: it described an answer from the other farm's records.
            pools.warm(_farm_key(farm_key))
            return farm_note_html(FARMS[_farm_key(farm_key)]), None, None

        # Then ask the same question again, so the two farms' answers can be
        # compared directly; with an empty box, just reset the panels.
        # .input, not .change: only a grower's own pick asks again.
        ask_chain(
            farm_picker.input,
            fill=switch_farm,
            fill_inputs=[farm_picker, question],
            fill_outputs=[farm_note, context_state, last_ask],
        )
        for b, q in example_buttons:
            ask_chain(b.click, fill=lambda q=q: q, fill_outputs=question)
        for b in followup_buttons:
            # The button's own label is the question it asks.
            ask_chain(b.click, fill=lambda label: label, fill_inputs=b, fill_outputs=question)

        # Registered after every ask above, so it cancels all of them.
        others = [c for c in ask_controls if c is not question]

        def clear(request: gr.Request):
            tickets.bump(request.session_hash or "")
            busy.release(request.session_hash or "")
            unlocked = dict(zip(map(id, ask_controls), unlock()))
            return (
                gr.update(value="", interactive=True),
                *_panels(empty_view()),
                None,
                *_followup_updates([]),
                None,
                *(unlocked[id(c)] for c in others),
            )

        clear_btn.click(
            clear,
            outputs=[question, *outputs, *others],
            cancels=ask_events,
            queue=False,
        )
        status_bottom = gr.HTML(bottom_html)
        app.load(status_panels, outputs=[status_top, status_bottom])

        gr.HTML(
            f'<p class="pf-muted" style="text-align:center;margin-top:8px">'
            f"Precision Farm {escape(__version__)} &middot; runs entirely on this computer "
            "&middot; looks back at your records, never predicts or recommends</p>"
        )
    return app


def theme() -> gr.themes.Base:
    wheat = gr.themes.Color(
        c50="#fbf5e6", c100="#f6e9c8", c200="#eed79a", c300="#e6c46c", c400="#dfb352",
        c500="#d9a441", c600="#b98829", c700="#9a6a1c", c800="#7a5216", c900="#5c3d11",
        c950="#3a260a", name="wheat",
    )
    system_sans = (
        "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"
    )
    return gr.themes.Base(
        primary_hue=wheat,
        secondary_hue=gr.themes.colors.blue,
        neutral_hue=gr.themes.colors.stone,
        radius_size=gr.themes.sizes.radius_lg,
        font=system_sans,
        font_mono=("ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"),
    ).set(
        button_primary_background_fill="#2e2219",
        button_primary_background_fill_hover="#4a3828",
        button_primary_text_color="#fbf7ee",
        button_primary_background_fill_dark="#d9a441",
        button_primary_background_fill_hover_dark="#e6c46c",
        button_primary_text_color_dark="#17130e",
        input_background_fill="#ffffff",
        input_background_fill_dark="#221c15",
        input_border_color_focus="#d9a441",
        block_background_fill="transparent",
        block_border_width="0px",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="farm-web",
        description=f"Precision Farm {__version__} -- the grower web app. "
        "Developers: the terminal CLI (farm-cli) is unchanged.",
    )
    p.add_argument("--port", type=int, default=7860)
    p.add_argument(
        "--lan",
        action="store_true",
        help="Listen on every network interface so other laptops on the same Wi-Fi can "
        "open it. Off by default: only this computer can reach the app.",
    )
    p.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_LOG)
    p.add_argument("--no-browser", action="store_true", help="Don't open a browser tab.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Start Farm 1's MCP servers now, while the page opens, so the first
    # question doesn't wait for them (about 7 s once, instead of about 4 s per
    # question). Farm 2's start the first time someone picks it.
    pools = FarmPools(args.audit_log)
    pools.warm(DEFAULT_FARM)
    app = build_app(args.audit_log, pools)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    if args.lan:
        print(
            "LAN mode: anyone on this network can open the app at "
            f"http://<this-computer's-IP>:{args.port} -- use only on a network you trust."
        )
    app.queue(default_concurrency_limit=1).launch(
        server_name=host,
        server_port=args.port,
        share=False,
        inbrowser=not args.no_browser,
        footer_links=[],
        ssr_mode=False,
        theme=theme(),
        css_paths=[Path(str(files("farm_web") / "static" / "theme.css"))],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
