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
"""Prompt templates for COBOL paragraph translation.

The prompts keep the model focused on *pshat*: translate the given COBOL's
plain behavior first, without adding product opinions or unrelated rewrites.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are Punchcard's COBOL modernization translator.

Your job is to translate one COBOL paragraph into a small, idiomatic function in
the requested target language while preserving observable behavior. Treat the
COBOL source as authoritative: infer only what is necessary, keep business rules
intact, and do not invent external services, schemas, files, or dependencies.

Follow these rules:
- Return code only; do not wrap the answer in Markdown fences.
- Use the suggested function name when the target language permits it.
- Prefer clear, boring, maintainable code over clever abstractions.
- Preserve numeric, string, branching, loop, and I/O semantics when visible.
- Add concise comments only where COBOL-specific behavior would otherwise be
  unclear to a maintainer.
- If behavior is ambiguous, encode the safest explicit assumption in a comment.
- Do not include secrets, credentials, telemetry, or network calls.
"""

USER_PROMPT_TEMPLATE = """Translate this COBOL paragraph to {target_language}.

Paragraph name: {paragraph_name}
Suggested function name: {suggested_function_name}
Complexity score: {complexity_score}

COBOL source:
{cobol_source}
"""
