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
import asyncio  # noqa: E402
from html import escape  # noqa: E402
from importlib.resources import files  # noqa: E402
from pathlib import Path  # noqa: E402

import gradio as gr  # noqa: E402

from farm_core.audit import AuditLog  # noqa: E402
from farm_host.cli import DEFAULT_AUDIT_LOG, AnswerResult, answer_question  # noqa: E402
from farm_host.mcp_client import ServerStartTimeout  # noqa: E402
from farm_host.preflight_cli import (  # noqa: E402
    DEFAULT_CONFIRM_STORE,
    DEFAULT_DATA_DIR,
    check_confirmed_mappings,
    check_model_pulled,
    check_ollama_running,
    check_synthetic_data,
)

from . import __version__  # noqa: E402
from .banner import BANNER_HTML, HOW_IT_WORKS_HTML  # noqa: E402
from .view import AnswerView, build_view, empty_view  # noqa: E402

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
            "Does the seed cost on Riverside in 2022 look right?",
            'What does "north eighty" refer to in 2017?',
        ),
    ),
)


def status_html() -> str:
    """The quick preflight checks (no server start, no model call), as chips."""
    ollama_check, pulled = check_ollama_running()
    checks = [
        ollama_check,
        check_model_pulled(pulled),
        check_synthetic_data(DEFAULT_DATA_DIR),
        check_confirmed_mappings(DEFAULT_CONFIRM_STORE),
    ]
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
    return (
        f'<div class="pf-status"><span class="pf-status-label">Ready check</span>{chips}</div>'
        f"{fix_list}"
    )


def _panels(view: AnswerView) -> tuple[str, str, str, str]:
    return view.answer_html, view.checks_html, view.figures_html, view.source_html


def make_ask(audit_log_path: Path):
    audit_log = AuditLog(audit_log_path)
    server_env = {"FARM_AUDIT_LOG": str(audit_log_path.resolve())}

    def ask(question: str) -> tuple[str, str, str, str]:
        question = (question or "").strip()
        if not question:
            return _panels(empty_view())
        try:
            # Sync handler on Gradio's worker thread, with its own event loop,
            # exactly like the CLI's asyncio.run().
            result = asyncio.run(answer_question(question, audit_log, env_overrides=server_env))
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
        return _panels(build_view(result))

    return ask


def build_app(audit_log_path: Path = DEFAULT_AUDIT_LOG) -> gr.Blocks:
    ask = make_ask(audit_log_path)
    empty = empty_view()

    with gr.Blocks(title="Precision Farm", analytics_enabled=False) as app:
        gr.HTML(BANNER_HTML)
        status = gr.HTML(status_html())
        gr.HTML(HOW_IT_WORKS_HTML)

        with gr.Row(equal_height=False):
            with gr.Column(scale=5, min_width=320):
                gr.HTML('<p class="pf-h">Ask a question</p>'
                        '<p class="pf-h-sub">About one of your fields and seasons.</p>')
                question = gr.Textbox(
                    show_label=False,
                    placeholder="e.g. Was East 80 a bad field or just a bad year?",
                    lines=2,
                    max_lines=4,
                    autofocus=True,
                )
                with gr.Row():
                    ask_btn = gr.Button("Ask my records", variant="primary", scale=3)
                    clear_btn = gr.Button("Clear", variant="secondary", scale=1)
                example_buttons: list[tuple[gr.Button, str]] = []
                for heading, qs in EXAMPLES:
                    gr.HTML(f'<p class="pf-eyebrow" style="margin-top:10px">{escape(heading)}</p>')
                    with gr.Column(elem_classes="pf-examples-group"):
                        for q in qs:
                            b = gr.Button(q, size="sm", elem_classes="pf-example")
                            example_buttons.append((b, q))
            with gr.Column(scale=7, min_width=340):
                answer = gr.HTML(empty.answer_html)

        with gr.Row(equal_height=False):
            with gr.Column(scale=4, min_width=300, elem_classes="pf-panel"):
                gr.HTML('<p class="pf-h">How we checked it</p>'
                        "<p class=\"pf-h-sub\">The AI's sentence is shown only if it passes "
                        "every one of these.</p>")
                checks = gr.HTML(empty.checks_html)
            with gr.Column(scale=6, min_width=320, elem_classes="pf-panel"):
                gr.HTML('<p class="pf-h">The numbers behind it</p>'
                        '<p class="pf-h-sub">Straight from your records, no AI involved.</p>')
                figures = gr.HTML(empty.figures_html)
                gr.HTML('<p class="pf-h" style="margin-top:12px">Where it came from</p>')
                source = gr.HTML(empty.source_html)

        outputs = [answer, checks, figures, source]
        ask_btn.click(ask, inputs=question, outputs=outputs)
        question.submit(ask, inputs=question, outputs=outputs)
        clear_btn.click(
            lambda: ("", *_panels(empty_view())), outputs=[question, *outputs], queue=False
        )
        for b, q in example_buttons:
            b.click(lambda q=q: q, outputs=question, queue=False).then(
                ask, inputs=question, outputs=outputs
            )
        app.load(status_html, outputs=status)

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
    app = build_app(args.audit_log)
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
