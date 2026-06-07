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
    """A single COBOL statement, with nested statements for block constructs.

    ``children`` holds the statements contained by a block statement: the bodies
    of ``IF``/``ELSE``, the ``WHEN`` branches of ``EVALUATE``, and inline
    ``PERFORM`` bodies. ``end_line`` is the source line of the statement's last
    token (equal to ``line_number`` for single-line statements).
    """

    verb: str
    text: str
    line_number: int
    tokens: tuple[str, ...] = field(default_factory=tuple)
    children: tuple[Statement, ...] = field(default_factory=tuple)
    end_line: int | None = None


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
class CopySpan:
    """A range of expanded-source lines that came from a copybook.

    ``start_line`` and ``end_line`` are 1-based, inclusive, and index into
    :attr:`CobolProgram.source` (the expanded text).
    """

    copybook: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class CobolProgram:
    """Top-level IR document for one COBOL program."""

    source: str
    identification: IdentificationDiv = field(default_factory=IdentificationDiv)
    environment: EnvironmentDiv = field(default_factory=EnvironmentDiv)
    data: DataDiv = field(default_factory=DataDiv)
    procedure: ProcedureDiv = field(default_factory=ProcedureDiv)
    copy_spans: tuple[CopySpan, ...] = field(default_factory=tuple)

    @property
    def program_id(self) -> str | None:
        """Return the PROGRAM-ID when present."""

        return self.identification.program_id

    def origin_of(self, line_number: int) -> str | None:
        """Return the copybook a given expanded-source line came from, if any."""

        for span in self.copy_spans:
            if span.start_line <= line_number <= span.end_line:
                return span.copybook
        return None

    @property
    def all_statements(self) -> Sequence[Statement]:
        """Flatten every statement, descending into nested block statements."""

        flat: list[Statement] = []

        def add(statements: Sequence[Statement]) -> None:
            for statement in statements:
                flat.append(statement)
                add(statement.children)

        add(self.procedure.statements)
        for section in self.procedure.sections:
            add(section.statements)
            for paragraph in section.paragraphs:
                add(paragraph.statements)
        for paragraph in self.procedure.paragraphs:
            add(paragraph.statements)
        return tuple(flat)
