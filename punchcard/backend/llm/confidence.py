"""Confidence scoring for COBOL paragraph modernization.

The scorer is intentionally conservative. It looks for COBOL constructs that
make automated modernization riskier, subtracts small explainable penalties, and
returns both the final score and the flags that explain it. Like a good beit
midrash note, every flag is meant to make review easier rather than mysterious.
"""

from __future__ import annotations

from typing import Final, NamedTuple

from punchcard.backend.parser.ir import DataDiv, Paragraph, Statement

BASE_SCORE: Final = 1.0
MANDATORY_REVIEW_THRESHOLD: Final = 0.6

GOTO_PENALTY: Final = 0.4
EXTERNAL_CALL_PENALTY: Final = 0.2
REDEFINES_PENALTY: Final = 0.15
ALTER_PENALTY: Final = 0.5
FILE_IO_PENALTY: Final = 0.1

FILE_IO_VERBS: Final = frozenset({"READ", "WRITE", "OPEN", "CLOSE"})


class ParagraphConfidence(NamedTuple):
    """Explainable confidence result for one paragraph.

    ``NamedTuple`` keeps the public API convenient for both attribute access
    (``result.score``) and tuple unpacking (``score, flags = result``).
    """

    score: float
    risk_flags: tuple[str, ...] = ()


def score_paragraph(paragraph: Paragraph, data_div: DataDiv | None = None) -> ParagraphConfidence:
    """Score a COBOL paragraph for automated modernization confidence.

    The score starts at ``1.0`` and deducts known-risk COBOL constructs:
    unstructured jumps, external calls, ``ALTER``, file I/O, and data-division
    ``REDEFINES``. The returned score is clamped to ``0.0`` through ``1.0``.

    Args:
        paragraph: Procedure paragraph to inspect.
        data_div: Optional data division used to detect ``REDEFINES`` risk.

    Returns:
        A :class:`ParagraphConfidence` containing the numeric score and stable
        risk flags. ``MANDATORY_REVIEW`` is added when the score is below 0.6.
    """

    score = BASE_SCORE
    risk_flags: list[str] = []

    for statement in paragraph.statements:
        if _is_go_to(statement):
            score -= GOTO_PENALTY
            risk_flags.append("GO_TO")

        if _is_external_call(statement):
            score -= EXTERNAL_CALL_PENALTY
            risk_flags.append("EXTERNAL_CALL")

        if statement.verb == "ALTER":
            score -= ALTER_PENALTY
            risk_flags.append("ALTER")

        if statement.verb in FILE_IO_VERBS:
            score -= FILE_IO_PENALTY
            risk_flags.append(f"FILE_IO_{statement.verb}")

    if data_div is not None and _data_div_has_redefines(data_div):
        score -= REDEFINES_PENALTY
        risk_flags.append("REDEFINES")

    score = _clamp_score(score)
    if score < MANDATORY_REVIEW_THRESHOLD:
        risk_flags.append("MANDATORY_REVIEW")

    return ParagraphConfidence(score=score, risk_flags=tuple(risk_flags))


def _is_go_to(statement: Statement) -> bool:
    """Return whether a statement is a COBOL GO TO jump."""

    return len(statement.tokens) >= 2 and statement.tokens[0] == "GO" and statement.tokens[1] == "TO"


def _is_external_call(statement: Statement) -> bool:
    """Return whether a statement appears to call an external routine."""

    return statement.verb == "CALL"


def _data_div_has_redefines(data_div: DataDiv) -> bool:
    """Return whether the data division uses COBOL REDEFINES."""

    return any("REDEFINES" in _tokens_from_text(line) for line in data_div.lines)


def _tokens_from_text(text: str) -> tuple[str, ...]:
    """Tokenize enough COBOL text for keyword detection without parsing deeply."""

    return tuple(part.upper() for part in text.replace(".", " ").split())


def _clamp_score(score: float) -> float:
    """Clamp a score into the public 0.0-1.0 confidence range."""

    return min(1.0, max(0.0, score))
