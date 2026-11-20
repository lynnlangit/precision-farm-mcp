""""What can I ask?": answered in code from the example list, before the AI
reads the question. Model-free: parse_question is replaced with a function
that fails the test if it is ever called for one of these questions.
"""

import pytest

from farm_core.audit import AuditLog
from farm_host import cli
from farm_host.examples import CAPABILITIES, EXAMPLES, is_capability_question

CAPABILITY_QUESTIONS = [
    "What are the retrospective questions you can answer - list them.",  # Lynn, 2026-11-20
    "What can I ask?",
    "what can you do",
    "What kinds of questions can you answer?",
    "Which questions can I ask?",
    "List the questions you answer",
    "Show me some example questions",
    "help",
]

RECORD_QUESTIONS = [q for _, qs in EXAMPLES for q in qs] + [
    "Was the north eighty a bad field or a bad year?",
    "What will next year's yield be?",
    "Why was 2020 bad on East 80?",
    "What did I spend on seed in 2023?",
]


@pytest.mark.parametrize("question", CAPABILITY_QUESTIONS)
def test_capability_questions_are_recognized(question):
    assert is_capability_question(question)


@pytest.mark.parametrize("question", RECORD_QUESTIONS)
def test_record_questions_are_not(question):
    assert not is_capability_question(question)


def test_one_example_per_type_from_the_shared_list():
    assert [h for h, _ in CAPABILITIES] == [h for h, _ in EXAMPLES]
    assert all(example == qs[0] for (_, example), (_, qs) in zip(CAPABILITIES, EXAMPLES))


async def test_answered_without_the_ai(tmp_path, monkeypatch):
    def no_parse(*args, **kwargs):
        raise AssertionError("the AI should not read a 'What can I ask?' question")

    monkeypatch.setattr(cli, "parse_question", no_parse)
    log = AuditLog(tmp_path / "audit.jsonl")
    result = await cli.answer_question(CAPABILITY_QUESTIONS[0], log)
    assert result.ok
    assert result.capabilities == CAPABILITIES
    assert result.query is None and result.narration is None
    for heading, example in CAPABILITIES:
        assert heading in result.text and example in result.text
    assert [e["event"] for e in log.entries()] == ["query", "capabilities_listed"]
