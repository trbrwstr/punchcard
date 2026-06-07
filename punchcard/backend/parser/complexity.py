"""Cyclomatic complexity scoring for COBOL paragraphs.

The score follows McCabe's definition: start at one linearly independent path
and add one for every decision point. COBOL spreads its decisions across a few
verbs and connectives, so the scorer counts the tokens that introduce a branch.
Like the rest of Punchcard's heuristics, it favors a number a reviewer can
re-derive by eye over anything clever.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from punchcard.backend.parser.ir import Paragraph, Statement

#: Tokens that each introduce one additional independent path.
DECISION_TOKENS: Final = frozenset(
    {
        "IF",
        "ELIF",
        "WHEN",
        "UNTIL",
        "VARYING",
        "TIMES",
        "AND",
        "OR",
    }
)

_TOKEN_RE = re.compile(r"[A-Z0-9_-]+", re.IGNORECASE)

BASE_COMPLEXITY: Final = 1


def cyclomatic_complexity(paragraph: Paragraph) -> int:
    """Return the cyclomatic complexity of a parsed paragraph."""

    return _score_tokens(token for statement in paragraph.statements for token in statement.tokens)


def complexity_for_statements(statements: Iterable[Statement]) -> int:
    """Return the cyclomatic complexity for a sequence of statements."""

    return _score_tokens(token for statement in statements for token in statement.tokens)


def complexity_for_source(source: str) -> int:
    """Return the cyclomatic complexity for raw COBOL paragraph text.

    Useful where only the persisted source string is available (for example the
    API layer, which stores paragraph text rather than the full IR).
    """

    return _score_tokens(match.group(0).upper() for match in _TOKEN_RE.finditer(source))


def _score_tokens(tokens: Iterable[str]) -> int:
    score = BASE_COMPLEXITY
    for token in tokens:
        if token.upper() in DECISION_TOKENS:
            score += 1
    return score
