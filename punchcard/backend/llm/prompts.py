"""Prompt rendering helpers for translation reviews."""

from __future__ import annotations

from punchcard.backend.parser.ir import CobolProgram
from punchcard.backend.review.confidence import ConfidenceScore


def render_translation_prompt(program: CobolProgram, confidence: ConfidenceScore) -> str:
    """Render a compact, source-grounded prompt for COBOL modernization.

    The prompt asks for auditable output and forbids invention. That is our
    little geder, a fence, around unsafe model behavior.
    """

    statements = "\n".join(
        f"- L{statement.line_number}: {statement.text}" for statement in program.all_statements
    )
    data_lines = "\n".join(f"- {line.strip()}" for line in program.data.lines[:20])
    reasons = "\n".join(f"- {reason}" for reason in confidence.reasons)

    return f"""You are modernizing COBOL with careful source citations.
Program: {program.program_id or "UNKNOWN"}
Confidence: {confidence.score:.3f} ({confidence.supported_statement_ratio:.3f} supported statement ratio)

Rules:
- Preserve business behavior before improving style.
- Cite COBOL source line numbers for important claims.
- Do not invent files, fields, or external calls.
- Flag ambiguous behavior instead of guessing.

Confidence reasons:
{reasons}

DATA DIVISION excerpt:
{data_lines or "- No DATA DIVISION lines captured."}

PROCEDURE statements:
{statements or "- No procedure statements captured."}

Return JSON with keys: summary, translated_code, risks, citations.
"""
