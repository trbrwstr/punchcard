"""Intermediate representation for parsed COBOL programs.

The IR is intentionally small: it captures the divisions, sections, paragraphs,
and statements needed by the first review pipeline without pretending to be a
complete COBOL AST. Like a good chevruta session, every node keeps source lines
nearby so later reviewers can argue from the text itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Statement:
    """A conservative representation of one COBOL statement."""

    verb: str
    text: str
    line_number: int
    tokens: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Paragraph:
    """A named paragraph inside a procedure division or section."""

    name: str
    line_number: int
    statements: tuple[Statement, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Section:
    """A named COBOL section with optional paragraphs."""

    name: str
    line_number: int
    paragraphs: tuple[Paragraph, ...] = field(default_factory=tuple)
    statements: tuple[Statement, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class IdentificationDiv:
    """Metadata found in the IDENTIFICATION DIVISION."""

    program_id: str | None = None
    entries: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EnvironmentDiv:
    """Raw source lines captured from the ENVIRONMENT DIVISION."""

    sections: tuple[Section, ...] = field(default_factory=tuple)
    lines: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DataDiv:
    """Raw source lines captured from the DATA DIVISION."""

    sections: tuple[Section, ...] = field(default_factory=tuple)
    lines: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ProcedureDiv:
    """Executable COBOL structure."""

    sections: tuple[Section, ...] = field(default_factory=tuple)
    paragraphs: tuple[Paragraph, ...] = field(default_factory=tuple)
    statements: tuple[Statement, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CobolProgram:
    """Top-level IR document for one COBOL program."""

    source: str
    identification: IdentificationDiv = field(default_factory=IdentificationDiv)
    environment: EnvironmentDiv = field(default_factory=EnvironmentDiv)
    data: DataDiv = field(default_factory=DataDiv)
    procedure: ProcedureDiv = field(default_factory=ProcedureDiv)

    @property
    def program_id(self) -> str | None:
        """Return the PROGRAM-ID when present."""

        return self.identification.program_id

    @property
    def all_statements(self) -> Sequence[Statement]:
        """Flatten procedure-level, section-level, and paragraph statements."""

        statements: list[Statement] = list(self.procedure.statements)
        for section in self.procedure.sections:
            statements.extend(section.statements)
            for paragraph in section.paragraphs:
                statements.extend(paragraph.statements)
        for paragraph in self.procedure.paragraphs:
            statements.extend(paragraph.statements)
        return tuple(statements)
