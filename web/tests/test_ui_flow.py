"""The question box and the "Ask my records" button, driven in a real browser.

What a grower can do with the box, and how many questions each action sends
(counted from the audit log, where every question is written once):

    typing, clicking away, pasting      -> nothing
    Enter                               -> the question, once
    Shift+Enter                         -> a new line, nothing sent
    "Ask my records"                    -> the question, once
    double click / Enter then click     -> once (controls lock while answering)
    empty or blank box                  -> nothing
    the same question again             -> asked again exactly as the first time
    Clear                               -> empties everything, drops an answer still on its way
    an example or "Ask next" button     -> fills the box and asks it, once
    switching farm                      -> asks the box's question of the other farm, once

By default the app runs with a stand-in for Gemma (tests/standin_gemma.py):
the servers, records and checks are real, only the two model calls are
scripted. On a Mac with Ollama, UI_REAL_GEMMA=1 runs the same tests against
gemma3:4b (slower; the content checks hold for it too).

    uv run --project web playwright install chromium     # once
    uv run --project web pytest -m ui web/tests -v
    UI_REAL_GEMMA=1 uv run --project web pytest -m ui web/tests -v

Needs both farms' records generated and ingested (see the README); skipped
otherwise.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui

playwright_api = pytest.importorskip("playwright.sync_api")

from farm_host.farms import FARMS  # noqa: E402

HERE = Path(__file__).resolve().parent
REAL_GEMMA = os.environ.get("UI_REAL_GEMMA") == "1"
# How long one answer may take: the stand-in takes ~2 s; gemma3:4b on a
# laptop CPU can take much longer.
ANSWER_TIMEOUT_MS = 240_000 if REAL_GEMMA else 60_000
ASK_LABEL = "Ask my records"
BUSY_LABEL = "Looking it up..."

EAST_80 = "Was East 80 a bad field or just a bad year?"
MARGINAL = "Was the Marginal Eighty a bad field or just a bad year?"
SOUTH_160 = "Was South 160 South a bad field or just a bad year?"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _records_ready() -> bool:
    return all(f.data_dir.exists() and f.confirm_store.exists() for f in FARMS.values())


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """The web app on a free port, with its own audit log."""
    if not _records_ready():
        pytest.skip("generate and ingest both farms first (README, 'Two example farms')")
    audit = tmp_path_factory.mktemp("ui") / "audit.jsonl"
    port = _free_port()
    args = ["--no-browser", "--port", str(port), "--audit-log", str(audit)]
    cmd = (
        [sys.executable, "-m", "farm_web.app", *args]
        if REAL_GEMMA
        else [sys.executable, str(HERE / "standin_gemma.py"), *args]
    )
    env = {**os.environ, "STANDIN_DELAY": os.environ.get("STANDIN_DELAY", "1.0")}
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            pytest.fail(f"farm-web exited early:\n{out[-3000:]}")
        try:
            urllib.request.urlopen(url, timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("farm-web didn't start within 120 s")
    yield url, audit
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        try:
            b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"no Chromium for Playwright ({e}); run `uv run --project web "
                        "playwright install chromium`")
        yield b
        b.close()


class Box:
    """One browser tab on the app, plus the audit log to count questions."""

    def __init__(self, page, audit: Path):
        self.page = page
        self.audit = audit
        self.text = page.locator("#pf-question textarea")
        self.ask = page.locator("#pf-ask")
        self.clear = page.locator("#pf-clear")
        self.answer = page.locator("#pf-answer")
        self.checks = page.locator("#pf-checks")
        self._seen = len(self._queries())

    def _queries(self) -> list[dict]:
        if not self.audit.exists():
            return []
        rows = [json.loads(line) for line in self.audit.read_text().splitlines() if line.strip()]
        return [r for r in rows if r.get("event") == "query"]

    def sent(self) -> list[dict]:
        """The questions sent since the last call (one audit 'query' row each)."""
        rows = self._queries()
        new, self._seen = rows[self._seen:], len(rows)
        return new

    def idle(self) -> None:
        """Wait until no question is being answered."""
        playwright_api.expect(self.ask).to_have_text(ASK_LABEL, timeout=ANSWER_TIMEOUT_MS)
        playwright_api.expect(self.ask).to_be_enabled(timeout=ANSWER_TIMEOUT_MS)
        self.page.wait_for_timeout(300)  # let the last outputs render

    def settle(self, ms: int = 1500) -> None:
        """Give a stray event the chance to fire, then wait for quiet."""
        self.page.wait_for_timeout(ms)
        self.idle()

    def type(self, question: str) -> None:
        self.text.click()
        self.text.fill("")
        self.text.press_sequentially(question, delay=5)

    def example(self, group: str, question: str) -> None:
        accordion = self.page.locator(".pf-example-group", has_text=group).first
        button = accordion.get_by_role("button", name=question, exact=True)
        if not button.is_visible():
            accordion.get_by_text(group).first.click()
        button.click()


@pytest.fixture
def box(app, browser):
    url, audit = app
    page = browser.new_page()  # a new tab: its own follow-up context
    page.goto(url)
    page.locator("#pf-question textarea").wait_for()
    b = Box(page, audit)
    yield b
    page.close()


# --- What sends a question, and how many times --------------------------------


def test_typing_and_clicking_away_sends_nothing(box):
    box.type(EAST_80)
    box.page.locator("body").click(position={"x": 5, "y": 5})  # blur
    box.text.click()
    box.page.wait_for_timeout(2500)
    assert box.sent() == []
    playwright_api.expect(box.answer).to_contain_text("Ask about one of your fields")


def test_enter_sends_the_question_once(box):
    box.type(MARGINAL)
    box.text.press("Enter")
    box.settle()
    sent = box.sent()
    assert [r["question"] for r in sent] == [MARGINAL]
    assert box.text.input_value() == MARGINAL  # Enter sent it; it didn't add a line
    playwright_api.expect(box.answer).to_contain_text("bad field")


def test_shift_enter_adds_a_line_and_sends_nothing(box):
    box.type("Was East 80")
    box.text.press("Shift+Enter")
    box.page.wait_for_timeout(2000)
    assert box.sent() == []
    assert box.text.input_value() == "Was East 80\n"


def test_button_sends_once_and_locks_while_answering(box):
    box.type(MARGINAL)
    box.ask.click()
    # While it's being answered the button says so and nothing can ask again.
    playwright_api.expect(box.ask).to_have_text(BUSY_LABEL)
    playwright_api.expect(box.ask).to_be_disabled()
    playwright_api.expect(box.text).to_be_disabled()
    box.idle()
    assert [r["question"] for r in box.sent()] == [MARGINAL]
    playwright_api.expect(box.text).to_be_enabled()


def test_double_click_sends_once(box):
    box.type(MARGINAL)
    box.ask.dblclick()
    box.settle(3000)
    assert len(box.sent()) == 1


def test_enter_then_click_sends_once(box):
    box.type(MARGINAL)
    box.text.press("Enter")
    box.ask.click(force=True, timeout=2000)  # lands on the locked button
    box.settle(3000)
    assert len(box.sent()) == 1
    # The refused second press shows no error, just the one answer.
    playwright_api.expect(box.page.locator(".toast-body")).to_have_count(0)
    playwright_api.expect(box.answer).to_contain_text("bad field")


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_or_blank_box_sends_nothing(box, text):
    box.text.fill(text)
    box.ask.click()
    box.settle()
    box.text.press("Enter")
    box.settle()
    assert box.sent() == []
    playwright_api.expect(box.answer).to_contain_text("Ask about one of your fields")


def test_asking_the_same_question_again_repeats_it_exactly(box):
    """The second press used to go to the parser as a follow-up to its own
    answer -- a different prompt, so it could come back different."""
    box.type(SOUTH_160)
    box.ask.click()
    box.idle()
    first_answer = box.answer.inner_text()
    box.ask.click()
    box.idle()
    sent = box.sent()
    assert [r["question"] for r in sent] == [SOUTH_160, SOUTH_160]
    assert all("follow_up_context" not in r for r in sent)
    assert box.answer.inner_text() == first_answer


def test_a_new_question_after_an_answer_is_a_follow_up(box):
    box.type(SOUTH_160)
    box.ask.click()
    box.idle()
    box.type("How dry was 2018?")
    box.ask.click()
    box.idle()
    second = box.sent()[-1]
    assert second["question"] == "How dry was 2018?"
    assert second["follow_up_context"]["field_name"] == "South 160 South"


def test_clear_empties_everything(box):
    box.type(SOUTH_160)
    box.ask.click()
    box.idle()
    box.clear.click()
    box.page.wait_for_timeout(500)
    assert box.text.input_value() == ""
    playwright_api.expect(box.answer).to_contain_text("Ask about one of your fields")
    # ...and the next question starts over: no follow-up context.
    box.sent()
    box.type("How dry was 2018?")
    box.ask.click()
    box.idle()
    assert "follow_up_context" not in box.sent()[-1]


def test_clear_drops_an_answer_still_on_its_way(box):
    box.type(SOUTH_160)
    box.ask.click()
    playwright_api.expect(box.ask).to_have_text(BUSY_LABEL)
    box.clear.click()
    playwright_api.expect(box.ask).to_have_text(ASK_LABEL)  # unlocked at once
    box.page.wait_for_timeout(6000 if not REAL_GEMMA else 30000)  # the lookup finishes...
    assert box.text.input_value() == ""
    playwright_api.expect(box.answer).to_contain_text("Ask about one of your fields")
    playwright_api.expect(box.answer).not_to_contain_text("Showing:")  # ...and is dropped


def test_example_button_fills_the_box_and_asks_once(box):
    box.example("Bad field or bad year?", MARGINAL)
    box.settle()
    assert [r["question"] for r in box.sent()] == [MARGINAL]
    assert box.text.input_value() == MARGINAL
    # Pressing the button afterwards asks it again, the same way.
    box.ask.click()
    box.idle()
    sent = box.sent()
    assert len(sent) == 1 and "follow_up_context" not in sent[0]


def test_examples_lock_while_answering(box):
    box.example("Bad field or bad year?", SOUTH_160)
    other = box.page.locator(".pf-example-group", has_text="Bad field or bad year?").get_by_role(
        "button", name=MARGINAL, exact=True
    )
    playwright_api.expect(other).to_be_disabled()
    box.settle()
    assert [r["question"] for r in box.sent()] == [SOUTH_160]
    assert box.text.input_value() == SOUTH_160  # the box shows what was answered


def test_ask_next_button_asks_once_as_a_follow_up(box):
    box.type(SOUTH_160)
    box.ask.click()
    box.idle()
    box.sent()
    follow = box.page.locator(".pf-followups-group button:visible").first
    label = follow.inner_text()
    follow.click()
    box.settle()
    sent = box.sent()
    assert [r["question"] for r in sent] == [label]
    assert sent[0]["follow_up_context"]["field_name"] == "South 160 South"
    assert box.text.input_value() == label


def test_switching_farm_asks_the_question_again_once(box):
    box.type(MARGINAL)
    box.ask.click()
    box.idle()
    box.sent()
    box.page.get_by_text(FARMS["farm2"].label, exact=True).click()
    playwright_api.expect(box.answer).to_contain_text("messy records", timeout=ANSWER_TIMEOUT_MS)
    box.settle()
    sent = box.sent()
    assert [r["question"] for r in sent] == [MARGINAL]
    assert "follow_up_context" not in sent[0]  # the other farm's answer isn't context


def test_switching_farm_with_an_empty_box_sends_nothing(box):
    box.page.get_by_text(FARMS["farm2"].label, exact=True).click()
    box.settle(3000)
    assert box.sent() == []


# --- What comes back: positive and negative eval questions --------------------

POSITIVE = [
    (MARGINAL, "bad field"),
    ("Which fields made money in 2019 and 2020?", "Depot Forty"),
    ("How dry was 2018?", "172.6"),
]

NEGATIVE = [
    # Out of scope: a prediction, not a look back at the records.
    "What will corn prices be next spring?",
    "Should I plant soybeans on East 80 next year?",
    # In scope, but no such field in the records.
    "Was Imaginary Quarter a bad field or just a bad year?",
]


@pytest.mark.parametrize("question,expected", POSITIVE)
def test_positive_questions_are_answered(box, question, expected):
    box.type(question)
    box.ask.click()
    box.idle()
    assert len(box.sent()) == 1
    playwright_api.expect(box.answer).to_contain_text(expected)
    playwright_api.expect(box.answer.locator(".pf-answer-refused")).to_have_count(0)


@pytest.mark.parametrize("question", NEGATIVE)
def test_negative_questions_are_refused(box, question):
    box.type(question)
    box.text.press("Enter")
    box.idle()
    assert len(box.sent()) == 1
    playwright_api.expect(box.answer.locator(".pf-answer-refused")).to_have_count(1)
    playwright_api.expect(box.answer).to_contain_text("I don't know")


def test_a_refusal_after_an_answer_keeps_the_page_usable(box):
    box.type(MARGINAL)
    box.ask.click()
    box.idle()
    box.type(NEGATIVE[0])
    box.ask.click()
    box.idle()
    playwright_api.expect(box.answer.locator(".pf-answer-refused")).to_have_count(1)
    box.type(MARGINAL)
    box.ask.click()
    box.idle()
    playwright_api.expect(box.answer).to_contain_text("bad field")
    assert len(box.sent()) == 3


def test_east_80_shows_the_ai_sentence_withheld(box):
    """Eval 2: the model blames the weather, which no record shows."""
    box.example("When the AI is stopped", EAST_80)
    box.settle()
    assert [r["question"] for r in box.sent()] == [EAST_80]
    playwright_api.expect(box.answer).to_contain_text("AI sentence withheld")
    playwright_api.expect(box.answer).to_contain_text("bad year")
    playwright_api.expect(box.checks).to_contain_text("withheld")
    # The same question typed and sent with the button gives the same result.
    box.type(EAST_80)
    box.ask.click()
    box.idle()
    playwright_api.expect(box.answer).to_contain_text("AI sentence withheld")
    assert len(box.sent()) == 1
