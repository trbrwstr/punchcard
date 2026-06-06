"""Minimal COBOL parser entry point.

This module deliberately starts with a conservative line-based parser. The name
is ANTLR-friendly so a generated listener can later feed the same IR without
changing callers. For now, the parser favors traceability and safe failure over
clever inference: unknown lines are preserved as statements when they appear in
PROCEDURE DIVISION and as raw text elsewhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from punchcard.backend.parser.ir import (
    CobolProgram,
    DataDiv,
    EnvironmentDiv,
    IdentificationDiv,
    Paragraph,
    ProcedureDiv,
    Section,
    Statement,
)

_DIVISION_RE = re.compile(r"^\s*([A-Z][A-Z0-9-]*)\s+DIVISION\s*\.?\s*$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^\s*([A-Z][A-Z0-9-]*)\s+SECTION\s*\.?\s*$", re.IGNORECASE)
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\s*\.\s*([A-Z0-9_-]+)\s*\.?\s*$", re.IGNORECASE)
_IDENT_ENTRY_RE = re.compile(r"^\s*([A-Z][A-Z0-9-]*)\s*\.\s*(.*?)\s*\.?\s*$", re.IGNORECASE)
_PARAGRAPH_RE = re.compile(r"^\s*([A-Z][A-Z0-9-]*)\s*\.\s*$", re.IGNORECASE)
_COMMENT_MARKERS = ("*", "/")
_STATEMENT_ONLY_WORDS = {
    "ADD",
    "CALL",
    "CLOSE",
    "COMPUTE",
    "DISPLAY",
    "DIVIDE",
    "ELSE",
    "END-EVALUATE",
    "END-IF",
    "EVALUATE",
    "GOBACK",
    "GO",
    "IF",
    "MOVE",
    "MULTIPLY",
    "OPEN",
    "PERFORM",
    "READ",
    "STOP",
    "SUBTRACT",
    "WHEN",
    "WRITE",
}


def parse_cobol(source: str) -> CobolProgram:
    """Parse COBOL source text into a small, review-oriented IR.

    Args:
        source: COBOL source as text.

    Returns:
        A :class:`CobolProgram` with divisions and procedure statements.
    """

    parser = _LineCobolParser(source)
    return parser.parse()


def parse_cobol_lines(lines: Iterable[str]) -> CobolProgram:
    """Parse COBOL source lines into a :class:`CobolProgram`."""

    return parse_cobol("\n".join(line.rstrip("\n") for line in lines))


class _LineCobolParser:
    """Small state machine for the first parser milestone."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.ident_entries: dict[str, str] = {}
        self.program_id: str | None = None
        self.environment_lines: list[str] = []
        self.data_lines: list[str] = []
        self.environment_sections: list[Section] = []
        self.data_sections: list[Section] = []
        self.procedure_sections: list[Section] = []
        self.procedure_paragraphs: list[Paragraph] = []
        self.procedure_statements: list[Statement] = []
        self._current_division: str | None = None
        self._current_section: Section | None = None
        self._current_paragraph: Paragraph | None = None

    def parse(self) -> CobolProgram:
        for line_number, raw_line in enumerate(self.source.splitlines(), start=1):
            line = _strip_sequence_area(raw_line).rstrip()
            if not line or _is_comment(line):
                continue

            division = _match_division(line)
            if division:
                self._start_division(division)
                continue

            if self._current_division == "IDENTIFICATION":
                self._parse_identification(line)
            elif self._current_division == "ENVIRONMENT":
                self._parse_non_procedure_line(line, line_number, self.environment_lines, self.environment_sections)
            elif self._current_division == "DATA":
                self._parse_non_procedure_line(line, line_number, self.data_lines, self.data_sections)
            elif self._current_division == "PROCEDURE":
                self._parse_procedure_line(line, line_number)

        return CobolProgram(
            source=self.source,
            identification=IdentificationDiv(program_id=self.program_id, entries=dict(self.ident_entries)),
            environment=EnvironmentDiv(sections=tuple(self.environment_sections), lines=tuple(self.environment_lines)),
            data=DataDiv(sections=tuple(self.data_sections), lines=tuple(self.data_lines)),
            procedure=ProcedureDiv(
                sections=tuple(self.procedure_sections),
                paragraphs=tuple(self.procedure_paragraphs),
                statements=tuple(self.procedure_statements),
            ),
        )

    def _start_division(self, division: str) -> None:
        self._current_division = division
        self._current_section = None
        self._current_paragraph = None

    def _parse_identification(self, line: str) -> None:
        program_id_match = _PROGRAM_ID_RE.match(line)
        if program_id_match:
            self.program_id = program_id_match.group(1).upper()
            self.ident_entries["PROGRAM-ID"] = self.program_id
            return

        entry_match = _IDENT_ENTRY_RE.match(line)
        if entry_match:
            key = entry_match.group(1).upper()
            value = entry_match.group(2).strip()
            if value:
                self.ident_entries[key] = value

    def _parse_non_procedure_line(
        self,
        line: str,
        line_number: int,
        raw_lines: list[str],
        sections: list[Section],
    ) -> None:
        raw_lines.append(line)
        section_name = _match_section(line)
        if section_name:
            sections.append(Section(name=section_name, line_number=line_number))

    def _parse_procedure_line(self, line: str, line_number: int) -> None:
        section_name = _match_section(line)
        if section_name:
            section = Section(name=section_name, line_number=line_number)
            self.procedure_sections.append(section)
            self._current_section = section
            self._current_paragraph = None
            return

        paragraph_name = _match_paragraph(line)
        if paragraph_name:
            paragraph = Paragraph(name=paragraph_name, line_number=line_number)
            if self._current_section is None:
                self.procedure_paragraphs.append(paragraph)
            else:
                self._current_section = _append_paragraph(self._current_section, paragraph)
                self.procedure_sections[-1] = self._current_section
            self._current_paragraph = paragraph
            return

        statement = _statement_from_line(line, line_number)
        if self._current_paragraph is not None:
            self._current_paragraph = _append_statement_to_paragraph(self._current_paragraph, statement)
            if self._current_section is None:
                self.procedure_paragraphs[-1] = self._current_paragraph
            else:
                self._current_section = _replace_last_paragraph(self._current_section, self._current_paragraph)
                self.procedure_sections[-1] = self._current_section
        elif self._current_section is not None:
            self._current_section = _append_statement_to_section(self._current_section, statement)
            self.procedure_sections[-1] = self._current_section
        else:
            self.procedure_statements.append(statement)


def _strip_sequence_area(line: str) -> str:
    """Remove fixed-format sequence columns when they look present."""

    if len(line) >= 7 and line[:6].strip().isdigit():
        return line[6:]
    return line


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return bool(stripped) and stripped[0] in _COMMENT_MARKERS


def _match_division(line: str) -> str | None:
    match = _DIVISION_RE.match(line)
    return match.group(1).upper() if match else None


def _match_section(line: str) -> str | None:
    match = _SECTION_RE.match(line)
    return match.group(1).upper() if match else None


def _match_paragraph(line: str) -> str | None:
    match = _PARAGRAPH_RE.match(line)
    if not match:
        return None
    name = match.group(1).upper()
    return None if name in _STATEMENT_ONLY_WORDS or name == "EXIT" else name


def _statement_from_line(line: str, line_number: int) -> Statement:
    normalized = line.strip().rstrip(".").strip()
    tokens = tuple(part.upper() for part in re.findall(r"[A-Z0-9_-]+", normalized, flags=re.IGNORECASE))
    verb = tokens[0] if tokens else "UNKNOWN"
    return Statement(verb=verb, text=normalized, line_number=line_number, tokens=tokens)


def _append_statement_to_paragraph(paragraph: Paragraph, statement: Statement) -> Paragraph:
    return replace(paragraph, statements=(*paragraph.statements, statement))


def _append_statement_to_section(section: Section, statement: Statement) -> Section:
    return replace(section, statements=(*section.statements, statement))


def _append_paragraph(section: Section, paragraph: Paragraph) -> Section:
    return replace(section, paragraphs=(*section.paragraphs, paragraph))


def _replace_last_paragraph(section: Section, paragraph: Paragraph) -> Section:
    return replace(section, paragraphs=(*section.paragraphs[:-1], paragraph))
