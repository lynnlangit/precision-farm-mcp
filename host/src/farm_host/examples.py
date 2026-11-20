"""The question types growers can ask, and the "What can I ask?" answer.

EXAMPLES is the one list of example questions: the web app shows it under
"Example questions (5 types)", and a question like "What can I ask?" gets it
back as a list. That answer is written here, in code: no AI reads the
question and nothing is looked up, so there is nothing to check.
"""

from __future__ import annotations

import re

# The eval questions (docs/EVAL_QUESTIONS.md), grouped the way a grower thinks.
EXAMPLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Bad field or bad year?",
        (
            "Was the Marginal Eighty a bad field or just a bad year?",
            "Was South 160 South a bad field or just a bad year?",
            # Third, not first: this is eval 2, the one gemma3:4b often
            # fails the checks on (it may blame "an unusual weather pattern",
            # which no record shows, so the sentence is withheld; it depends
            # on the model's output -- see host/tests/test_eval_nl.py -k
            # withheld). The group opens on two answers that pass.
            "Was East 80 a bad field or just a bad year?",
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
)

EXAMPLES_LABEL = f"Example questions ({len(EXAMPLES)} types)"

# One example per type for the "What can I ask?" answer: the first of each
# group, which is also the one the web app lists first.
CAPABILITIES: tuple[tuple[str, str], ...] = tuple((h, qs[0]) for h, qs in EXAMPLES)

# Questions about the tool itself, not about a field. Kept narrow on purpose:
# each pattern needs the question to be about "questions" / "asking" / what
# "you can do", so a records question ("Which fields made money?") never
# matches. Checked on the lower-cased question with punctuation removed.
_CAPABILITY_PATTERNS = tuple(
    re.compile(p)
    for p in (
        # "What are the retrospective questions you can answer - list them."
        # "What kinds of questions can I ask?"
        r"\b(what|which)\b.*\bquestions?\b.*\b(can|could|do|does|will|should|may)\b.*\b(answer|ask|handle)\b",
        r"\b(what|which)\b.*\bquestions?\b.*\b(you|it|this)\b.*\b(answer|handle|know)\b",
        # "What can I ask?", "What can you do?", "What can you answer?"
        r"\bwhat (can|could|should|do) (i|you|we) (ask|answer|do|help)\b",
        r"\bwhat (is|are) (this|you|it) (for|able to do)\b",
        # "List the questions", "Show me example questions"
        r"\b(list|show|give)\b( me)?( the| all| your| some| a few)?( \w+)? questions\b",
        r"\bexample questions?\b",
        r"\bhow do i use (this|you|it)\b",
        r"^(help|help me|menu|options)$",
    )
)


def _normalize(question: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", question.lower()).split())


def is_capability_question(question: str) -> bool:
    """True for "What can I ask?"-style questions about the tool itself."""
    q = _normalize(question)
    return any(p.search(q) for p in _CAPABILITY_PATTERNS)


def capabilities_text(first_season: int, last_season: int) -> str:
    """The plain-text answer (what the terminal prints)."""
    lines = [
        f"I answer {len(CAPABILITIES)} kinds of questions about your own records "
        f"({first_season}-{last_season}). One example of each:",
        "",
    ]
    lines += [f"- {heading}  e.g. \"{example}\"" for heading, example in CAPABILITIES]
    lines += [
        "",
        "I only look back at your records: I don't predict, recommend, or explain terms.",
    ]
    return "\n".join(lines)
