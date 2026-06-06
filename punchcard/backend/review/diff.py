"""Utilities for producing reviewer-friendly text diffs."""

from __future__ import annotations

import difflib


def _normalize_line_endings(text: str) -> str:
    """Return text with Unix line endings, so CRLF noise stays out of reviews."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def generate_unified_diff(
    original: str,
    suggested: str,
    fromfile: str = "original.cob",
    tofile: str = "translated.py",
) -> str:
    """Generate a unified diff for human review.

    Line endings are normalized before diffing so platform differences do not
    create needless churn. Five context lines give reviewers enough surrounding
    code to understand the change without overwhelming them.
    """
    original_lines = _normalize_line_endings(original).splitlines(keepends=True)
    suggested_lines = _normalize_line_endings(suggested).splitlines(keepends=True)

    return "".join(
        difflib.unified_diff(
            original_lines,
            suggested_lines,
            fromfile=fromfile,
            tofile=tofile,
            n=5,
        )
    )
