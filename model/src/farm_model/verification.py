"""Proves the narrator's structural constraint actually holds: every number
that appears in a narration must be traceable to the payload it was given --
either a value that was literally in there, or a plain count/derived fact
(e.g. "3 fields") of something in there. A number that can't be traced is
evidence the model computed or invented something, which the design is
supposed to make impossible.
"""

from __future__ import annotations

import dataclasses
import re

# (?<!\d) stops a range separator like "2021-2025" from being read as a
# negative sign on 2025 -- a real minus is never immediately preceded by a
# digit, a range hyphen always is.
_NUMBER_RE = re.compile(r"(?<!\d)-?\$?[\d,]+\.?\d*%?")
_ROUNDING_TOLERANCE = 0.02  # 2% relative tolerance for narrated rounding ("about $27,300")


def _parse_number(token: str) -> float | None:
    cleaned = token.replace("$", "").replace(",", "").replace("%", "")
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_numbers(text: str) -> set[float]:
    numbers = set()
    for token in _NUMBER_RE.findall(text):
        value = _parse_number(token)
        if value is not None:
            numbers.add(value)
    return numbers


def _flatten_payload_numbers(payload: object, seasons_as_numbers: set[float]) -> None:
    if isinstance(payload, bool):
        return
    if isinstance(payload, (int, float)):
        seasons_as_numbers.add(float(payload))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key.isdigit():
                seasons_as_numbers.add(float(key))
            _flatten_payload_numbers(value, seasons_as_numbers)
        seasons_as_numbers.add(float(len(payload)))
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            _flatten_payload_numbers(value, seasons_as_numbers)
        seasons_as_numbers.add(float(len(payload)))
    elif isinstance(payload, str):
        for value in extract_numbers(payload):
            seasons_as_numbers.add(value)


def grounded_numbers(payload: object) -> set[float]:
    """Every number derivable from the payload: literal values, season years
    used as dict keys, and list/dict lengths (so "3 fields" narrating
    len(results) == 3 counts as grounded, not invented).
    """
    numbers: set[float] = set()
    _flatten_payload_numbers(payload, numbers)
    return numbers


@dataclasses.dataclass(frozen=True)
class GroundingResult:
    ungrounded_numbers: list[float]

    @property
    def is_grounded(self) -> bool:
        return not self.ungrounded_numbers


# Numeric grounding alone can't catch this: a narration can cite only real
# payload numbers and still draw the *opposite* conclusion from a categorical
# verdict field. Observed for real from gemma3:4b on a loss_rate=1.0
# bad_field payload, in two different phrasings:
#   "...it appears the issue was likely due to a bad year rather than a
#   specific field problem."
#   "...Therefore, based on this evidence, it appears to have been a bad
#   year for this field."
# An exact-phrase marker list caught the first and missed the second --
# whack-a-mole against paraphrasing doesn't scale. Instead: does the
# narration conclude with the *other* category's language, unnegated? A
# correct bad_field narration may still say "not a bad year" (negated,
# fine); it should not conclude "it was a bad year" outright.
_NEGATION_CUES = ("not ", "n't ", "rather than", "instead of", "as opposed to", "isn't", "wasn't")
# Deliberately just the literal conclusion phrase, not broader descriptive
# language like "chronically" or "consistently poor" -- those describe the
# symptom and show up in narrations of *either* verdict, so treating them as
# an assertion of "bad_field" specifically let an unnegated "bad year"
# conclusion slip through in testing (the descriptive phrase earlier in the
# text satisfied "asserts_correct" and masked the contradicting conclusion).
_CATEGORY_PHRASES = {
    "bad_field": ("bad field",),
    "bad_year": ("bad year",),
}
_OTHER_CATEGORY = {"bad_field": "bad_year", "bad_year": "bad_field"}


def _mentioned_unnegated(text: str, phrases: tuple[str, ...]) -> bool:
    for phrase in phrases:
        idx = text.find(phrase)
        if idx == -1:
            continue
        window = text[max(0, idx - 40) : idx]
        if not any(cue in window for cue in _NEGATION_CUES):
            return True
    return False


def check_verdict_not_contradicted(narration: str, payload: object) -> bool:
    """True unless the narration asserts, unnegated, the category opposite
    the payload's own "verdict" field without also asserting the correct
    one. Payloads without a "verdict" key (or a verdict outside bad_field/
    bad_year) always pass.
    """
    if not isinstance(payload, dict) or "verdict" not in payload:
        return True
    verdict = payload["verdict"]
    if verdict == "consistently_profitable":
        lowered = narration.lower()
        return not any(
            p in lowered for p in ("was a bad field", "was a bad year", "lost money overall")
        )
    if verdict not in _CATEGORY_PHRASES:
        return True

    lowered = narration.lower()
    other = _OTHER_CATEGORY[verdict]
    asserts_other = _mentioned_unnegated(lowered, _CATEGORY_PHRASES[other])
    asserts_correct = _mentioned_unnegated(lowered, _CATEGORY_PHRASES[verdict])
    return not (asserts_other and not asserts_correct)


def check_narration_grounded(
    narration: str, payload: object, question: str | None = None
) -> GroundingResult:
    """question, if given, contributes its own numbers to the grounded set --
    a field name like "East 80" or "N 80" is allowed to be echoed back even
    though it isn't itself a data value in the payload. Restating the
    subject of the question is not the same as inventing a fact about it.
    """
    narration_numbers = extract_numbers(narration)
    payload_numbers = grounded_numbers(payload)
    if question:
        payload_numbers |= extract_numbers(question)

    def _close(a: float, b: float) -> bool:
        return a == b or (b != 0 and abs(a - b) / abs(b) <= _ROUNDING_TOLERANCE)

    ungrounded = []
    for n in sorted(narration_numbers):
        # A payload figure of -95000 grounds a narration saying "lost 95000"
        # just as well as "-95000" -- signed-to-magnitude is a legitimate
        # restatement, not an invented number.
        if any(_close(n, p) or _close(n, abs(p)) for p in payload_numbers):
            continue
        ungrounded.append(n)

    return GroundingResult(ungrounded_numbers=ungrounded)
