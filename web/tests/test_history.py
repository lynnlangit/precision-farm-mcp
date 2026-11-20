"""Session history (farm_web.history): the audit log read back one question
at a time, grouped into sessions. Built from hand-written log entries, so no
servers or model are needed."""

import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from farm_core.audit import AuditLog
from farm_web import app as web_app
from farm_web.history import history_page, questions_from, sessions_from

T0 = datetime.datetime(2026, 11, 19, 23, 0, tzinfo=datetime.timezone.utc)


def _write(path, rows):
    """rows: (minutes after T0, event, fields). Writes a real hash-chained log
    with the given timestamps."""
    log = AuditLog(path)
    for minutes, event, fields in rows:
        entry = log.log(event, **fields)
        when = (T0 + datetime.timedelta(minutes=minutes)).isoformat()
        _retime(path, entry["hash"], when)
    return log


def _retime(path, entry_hash, when):
    # Rewrite the last line's timestamp and re-chain it, as if it had been
    # logged then: the page reads timestamps, and verify() must still pass.
    import hashlib
    import json

    lines = path.read_text().splitlines()
    entry = json.loads(lines[-1])
    assert entry["hash"] == entry_hash
    entry.pop("hash")
    entry["timestamp"] = when
    canon = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    entry["hash"] = hashlib.sha256(canon.encode()).hexdigest()
    lines[-1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")


def _shown(minute, question, session="web-a", farm="farm1"):
    labels = {"source": "web", "farm": farm, "session_id": session} if session else {}
    return [
        (minute, "query", {"question": question, **labels}),
        (minute, "parsed", {"intent": "bad_field_or_bad_year", "field_name": "East 80", "season": None}),
        (minute, "tool_call", {"server": "report-export", "tool": "bad_field_or_bad_year",
                               "args": {"field_name": "East 80"}}),
        (minute + 0.1, "narration", {"question": question, "model_context_shown": True,
                                     "failed_checks": [], "rejected_texts": [], "used_fallback": False,
                                     "lead": "East 80 had a bad year.",
                                     "shown_text": "Profit was low in 2020."}),
    ]


def _withheld(minute, question, session="web-a"):
    labels = {"source": "web", "farm": "farm1", "session_id": session} if session else {}
    return [
        (minute, "query", {"question": question, **labels}),
        (minute, "parsed", {"intent": "season_weather", "season": 2018}),
        (minute, "tool_call", {"server": "weather-history", "tool": "get_season_weather",
                               "args": {"season": 2018}}),
        (minute + 0.1, "narration", {"question": question, "model_context_shown": False,
                                     "failed_checks": [["season_count"]],
                                     "rejected_texts": ["Drier than the last <b>ten</b> years."],
                                     "used_fallback": True, "lead": "2018 was dry.",
                                     "shown_text": None}),
    ]


def _refused(minute, question, session="web-a"):
    labels = {"source": "web", "farm": "farm2", "session_id": session} if session else {}
    return [
        (minute, "query", {"question": question, **labels}),
        (minute, "parse_refused", {"question": question, "kind": "unresolved_followup", "reason": "r"}),
    ]


def test_questions_group_by_session_id_and_older_entries_by_time(tmp_path):
    path = tmp_path / "audit.jsonl"
    rows = (
        _shown(0, "old one", session=None)
        + _shown(10, "old two", session=None)  # 10 min later: same unlabelled session
        + _shown(120, "old three", session=None)  # 2 h later: a new one
        + _shown(200, "web one", session="web-a")
        + _withheld(201, "web two", session="web-a")
        + _refused(202, "web three", session="web-a")
    )
    log = _write(path, rows)
    assert log.verify()
    sessions = sessions_from(questions_from(log.entries()))
    assert [len(s.questions) for s in sessions] == [2, 1, 3]
    assert [s.labelled for s in sessions] == [False, False, True]
    assert sessions[-1].key == "web-a"
    assert [q.outcome for q in sessions[-1].questions] == ["shown", "withheld", "refused"]
    assert sessions[-1].farms == ["Farm 1", "Farm 2"]
    assert "Web app" in sessions[-1].label() and "3 questions" in sessions[-1].label()
    assert "grouped by time" in sessions[0].label()


def test_page_shows_what_was_read_and_withheld(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, _shown(0, "old one", session=None) + _shown(100, "East 80?") + _withheld(101, "How dry was 2018?"))
    page = history_page(path)
    assert "Log intact." in page
    assert "East 80?" in page
    assert "Profit was low in 2020." in page  # the blue sentence that was shown
    assert "East 80 had a bad year." in page  # the green lead
    # The withheld sentence is shown crossed out, escaped, with the check that blocked it.
    assert "<s>Drier than the last &lt;b&gt;ten&lt;/b&gt; years.</s>" in page
    assert "Any count of years or seasons matches your records" in page
    assert page.count('class="chk fail"') == 1


def test_picking_an_older_session(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, _shown(0, "old one", session=None) + _shown(100, "new one"))
    old_key = sessions_from(questions_from(AuditLog(path).entries()))[0].key
    page = history_page(path, old_key)
    assert "old one</div>" in page or "old one<" in page
    assert "Grouped by time" in page


def test_older_entries_say_what_was_not_saved(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [
        (0, "query", {"question": "was the north eighty a bad field"}),
        (0, "tool_call", {"tool": "bad_field_or_bad_year", "args": {}}),
        (0, "narration", {"question": "q", "grounded": True, "used_fallback": False, "attempts": 1}),
    ])
    page = history_page(path)
    assert "The shown sentence wasn" in page
    assert "Which checks ran wasn" in page


def test_a_changed_log_is_flagged(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, _shown(0, "East 80?"))
    path.write_text(path.read_text().replace("East 80 had a bad year.", "East 80 had a great year."))
    page = history_page(path)
    assert "Log changed." in page and "Log intact." not in page


def test_empty_log(tmp_path):
    assert "No questions in the log yet" in history_page(tmp_path / "audit.jsonl")


def test_history_route_serves_the_page(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, _shown(0, "East 80?"))
    server = FastAPI()

    @server.get("/{rest:path}")
    def catch_all(rest: str):  # stands in for a route that would otherwise answer first
        return {"not": "history"}

    web_app.add_history_route(server, path)
    response = TestClient(server).get("/history")
    assert response.status_code == 200
    assert "Question flow" in response.text and "East 80?" in response.text


def test_every_web_question_carries_the_same_session(monkeypatch, tmp_path):
    import asyncio

    from farm_host.cli import AnswerResult

    class _Pool:
        def run(self, fn):
            return asyncio.run(fn(None))

    pools = web_app.FarmPools(tmp_path / "audit.jsonl", factory=lambda farm: _Pool())
    seen = []

    async def fake(question, audit_log, env_overrides=None, context=None, fleet=None, **labels):
        seen.append(labels)
        return AnswerResult(text="no", ok=False, refusal_kind="out_of_scope")

    monkeypatch.setattr(web_app, "answer_question", fake)
    ask = web_app.make_ask(tmp_path / "audit.jsonl", pools)
    ask("one", None, "farm1")
    ask("two", None, "farm2")
    assert [s["source"] for s in seen] == ["web", "web"]
    assert [s["farm"] for s in seen] == ["farm1", "farm2"]
    assert seen[0]["session_id"] == seen[1]["session_id"]
    assert seen[0]["session_id"].startswith("web-")


def _flow(tmp_path, rows):
    from farm_web.flowmap import build_flow

    path = tmp_path / "audit.jsonl"
    _write(path, rows)
    return build_flow(questions_from(AuditLog(path).entries()))


def test_the_map_counts_every_step_a_question_passed(tmp_path):
    tool_refused = [
        (300, "query", {"question": "Marginal 80?"}),
        (300, "parsed", {"intent": "bad_field_or_bad_year", "field_name": "Marginal 80"}),
        (300, "tool_call", {"server": "report-export", "tool": "bad_field_or_bad_year", "args": {}}),
        (300, "tool_refused", {"server": "report-export", "tool": "bad_field_or_bad_year", "code": "not_found"}),
    ]
    flow = _flow(
        tmp_path,
        _shown(0, "a") + _shown(1, "b") + _withheld(2, "c") + _refused(3, "d") + tool_refused,
    )
    n, e = flow.nodes, flow.edges
    assert n["ask"].count == 5 and n["reader"].count == 5 and n["reader"].trouble == 1
    assert n["report-export"].count == 3 and n["report-export"].trouble == 1
    assert n["weather-history"].count == 1
    assert n["writer"].count == 3 and n["checks"].count == 3 and n["checks"].trouble == 1
    assert (n["shown"].count, n["withheld"].count, n["refused"].count) == (2, 1, 2)
    assert e[("reader", "refused")] == 1 and e[("report-export", "refused")] == 1
    assert e[("report-export", "writer")] == 2 and e[("checks", "withheld")] == 1
    assert ("Any count of years or seasons matches your records", "blocked 1") in n["checks"].details


def test_old_tool_calls_without_a_server_still_land_on_one(tmp_path):
    flow = _flow(tmp_path, [
        (0, "query", {"question": "q"}),
        (0, "tool_call", {"tool": "get_cost_ledger_row", "args": {}}),
        (0, "narration", {"question": "q", "used_fallback": False}),
    ])
    assert flow.nodes["cost-ledger"].count == 1


def test_all_time_is_the_default_and_a_session_narrows_it(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, _shown(0, "old one", session=None) + _shown(100, "new one"))
    everything = history_page(path)
    assert 'value="all" selected' in everything and "2 questions ·" in everything
    newest = sessions_from(questions_from(AuditLog(path).entries()))[-1].key
    one = history_page(path, newest)
    assert "1 question ·" in one
    assert 'class="flowmap"' in one


def test_one_link_only_at_the_bottom_of_the_app(tmp_path):
    config = repr(web_app.build_app(tmp_path / "audit.jsonl").config)
    assert config.count("/history") == 1
    assert "Question flow" in config
