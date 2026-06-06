"""Confidence scoring for Punchcard's first-pass COBOL reviews.

The score is intentionally explainable rather than clever. Like pshat before
pilpul, callers can see which source facts increased or reduced confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from punchcard.backend.parser.ir import CobolProgram

SUPPORTED_VERBS = frozenset(
    {
        "MOVE",
        "ADD",
        "SUBTRACT",
        "MULTIPLY",
        "DIVIDE",
        "COMPUTE",
        "IF",
        "ELSE",
        "END-IF",
        "PERFORM",
        "EVALUATE",
        "WHEN",
        "CALL",
        "READ",
        "WRITE",
        "OPEN",
        "CLOSE",
        "STOP",
        "GOBACK",
        "GO",
        "DISPLAY",
        "END-EVALUATE",
    }
)

CONTROL_FLOW_VERBS = frozenset({"IF", "ELSE", "END-IF", "PERFORM", "EVALUATE", "WHEN", "GO"})
IO_VERBS = frozenset({"READ", "WRITE", "OPEN", "CLOSE"})


@dataclass(frozen=True, slots=True)
class ConfidenceScore:
    """Explainable parser/review confidence result."""

    score: float
    supported_statement_ratio: float
    total_statements: int
    reasons: tuple[str, ...] = field(default_factory=tuple)


def score_program_confidence(program: CobolProgram) -> ConfidenceScore:
    """Score how ready a parsed program is for LLM-assisted translation.

    The metric favors traceable structure, supported verbs, and balanced
    COBOL block markers. It deliberately returns a bounded value in ``[0, 1]``
    so API clients can make simple product decisions.
    """

    statements = tuple(program.all_statements)
    total = len(statements)
    if total == 0:
        return ConfidenceScore(
            score=0.0,
            supported_statement_ratio=0.0,
            total_statements=0,
            reasons=("No procedure statements were parsed.",),
        )

    supported_count = sum(1 for statement in statements if statement.verb in SUPPORTED_VERBS)
    supported_ratio = supported_count / total
    score = 0.45 + (0.45 * supported_ratio)
    reasons: list[str] = [f"{supported_count}/{total} statements use supported MVP verbs."]

    if program.program_id:
        score += 0.03
        reasons.append("PROGRAM-ID is present.")
    else:
        score -= 0.08
        reasons.append("PROGRAM-ID is missing.")

    if program.data.sections:
        score += 0.02
        reasons.append("DATA DIVISION sections were captured.")

    verbs = [statement.verb for statement in statements]
    if any(verb in CONTROL_FLOW_VERBS for verb in verbs):
        score += 0.02
        reasons.append("Control-flow statements are represented in the IR.")
    if any(verb in IO_VERBS for verb in verbs):
        score += 0.02
        reasons.append("File I/O statements are represented in the IR.")

    if verbs.count("IF") != verbs.count("END-IF"):
        score -= 0.12
        reasons.append("IF and END-IF counts are not balanced.")
    if verbs.count("EVALUATE") != verbs.count("END-EVALUATE"):
        score -= 0.12
        reasons.append("EVALUATE and END-EVALUATE counts are not balanced.")

    bounded_score = max(0.0, min(1.0, round(score, 3)))
    return ConfidenceScore(
        score=bounded_score,
        supported_statement_ratio=round(supported_ratio, 3),
        total_statements=total,
        reasons=tuple(reasons),
    )
