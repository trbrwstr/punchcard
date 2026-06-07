"""COBOL parser entry point backed by an ANTLR4 COBOL85 grammar.

The parser uses the vendored ANTLR-generated lexer/parser in ``_generated`` (built
from ``grammar/Cobol85.g4``) and walks the resulting parse tree into Punchcard's
small IR. The walk is deliberately shallow: it captures divisions, the section
names reviewers cite, paragraphs, and statements — with block statements
(``IF``/``EVALUATE``/inline ``PERFORM``) carrying their nested statements as
``Statement.children`` so the structure is preserved without modeling a full
control-flow graph.

Parsing is best-effort: ANTLR's error recovery still yields a tree on malformed
input, and the walk simply captures whatever it produced.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from antlr4 import CommonTokenStream, InputStream, ParserRuleContext
from antlr4.error.ErrorListener import ErrorListener

from punchcard.backend.parser._generated.Cobol85Lexer import Cobol85Lexer
from punchcard.backend.parser._generated.Cobol85Parser import Cobol85Parser
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
from punchcard.backend.parser.preprocessor import preprocess

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")


def parse_cobol(source: str, *, copybook_paths: Iterable[str | Path] = ()) -> CobolProgram:
    """Parse COBOL source text into Punchcard's review-oriented IR.

    ``COPY``/``REPLACE`` are expanded first (see
    :func:`punchcard.backend.parser.preprocessor.preprocess`); copybooks are
    resolved from ``copybook_paths``. Line numbers in the IR refer to the
    expanded source, which is also what :attr:`CobolProgram.source` stores.
    """

    expanded = preprocess(source, copybook_paths=copybook_paths)
    lexer = Cobol85Lexer(InputStream(expanded))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_SilentErrorListener())
    parser = Cobol85Parser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(_SilentErrorListener())

    tree = parser.startRule()
    source_lines = expanded.splitlines()
    program_unit = _first(tree, "programUnit")
    if program_unit is None:
        return CobolProgram(source=expanded)

    return CobolProgram(
        source=expanded,
        identification=_identification(program_unit),
        environment=_environment(program_unit, source_lines),
        data=_data(program_unit, source_lines),
        procedure=_procedure(program_unit),
    )


def parse_cobol_lines(lines: Iterable[str], *, copybook_paths: Iterable[str | Path] = ()) -> CobolProgram:
    """Parse COBOL source lines into a :class:`CobolProgram`."""

    return parse_cobol("\n".join(line.rstrip("\n") for line in lines), copybook_paths=copybook_paths)


class _SilentErrorListener(ErrorListener):
    """Swallow syntax errors so parsing stays best-effort and side-effect free."""

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e) -> None:  # noqa: N802
        return None


# --- division builders -------------------------------------------------------


def _identification(program_unit: ParserRuleContext) -> IdentificationDiv:
    paragraph = _first(program_unit, "programIdParagraph")
    if paragraph is None:
        return IdentificationDiv()
    name_ctx = _first(paragraph, "programName")
    if name_ctx is None:
        return IdentificationDiv()
    name = _ctx_text(name_ctx).strip().strip("\"'").upper()
    return IdentificationDiv(program_id=name, entries={"PROGRAM-ID": name})


def _environment(program_unit: ParserRuleContext, source_lines: list[str]) -> EnvironmentDiv:
    division = _first(program_unit, "environmentDivision")
    if division is None:
        return EnvironmentDiv()
    return EnvironmentDiv(
        sections=_section_names(division),
        lines=_division_lines(division, source_lines),
    )


def _data(program_unit: ParserRuleContext, source_lines: list[str]) -> DataDiv:
    division = _first(program_unit, "dataDivision")
    if division is None:
        return DataDiv()
    return DataDiv(
        sections=_section_names(division),
        lines=_division_lines(division, source_lines),
    )


def _procedure(program_unit: ParserRuleContext) -> ProcedureDiv:
    division = _first(program_unit, "procedureDivision")
    if division is None:
        return ProcedureDiv()
    body = _first(division, "procedureDivisionBody")
    if body is None:
        return ProcedureDiv()

    paragraphs = tuple(_build_paragraph(p) for p in _loose_paragraphs(body))
    sections = tuple(
        Section(
            name=_section_header_name(section),
            line_number=section.start.line,
            paragraphs=tuple(_build_paragraph(p) for p in _loose_paragraphs(section)),
        )
        for section in _children_named(body, "procedureSection")
    )
    return ProcedureDiv(paragraphs=paragraphs, sections=sections)


# --- paragraph / statement builders -----------------------------------------


def _build_paragraph(paragraph_ctx: ParserRuleContext) -> Paragraph:
    name_ctx = _first(paragraph_ctx, "paragraphName")
    name = (name_ctx.start.text if name_ctx is not None else paragraph_ctx.start.text).upper()
    statements: list[Statement] = []
    for sentence in _children_named(paragraph_ctx, "sentence"):
        for statement_ctx in _children_named(sentence, "statement"):
            statements.append(_build_statement(statement_ctx))
    return Paragraph(name=name, line_number=paragraph_ctx.start.line, statements=tuple(statements))


def _build_statement(statement_ctx: ParserRuleContext) -> Statement:
    text = " ".join(_ctx_text(statement_ctx).split())
    children = tuple(_build_statement(child) for child in _nested_statements(statement_ctx))
    stop = statement_ctx.stop or statement_ctx.start
    return Statement(
        verb=statement_ctx.start.text.upper(),
        text=text,
        line_number=statement_ctx.start.line,
        tokens=tuple(match.group(0).upper() for match in _TOKEN_RE.finditer(text)),
        children=children,
        end_line=stop.line,
    )


# --- tree helpers ------------------------------------------------------------


def _rule_name(ctx: ParserRuleContext) -> str:
    name = type(ctx).__name__[:-7]  # strip "Context"
    return name[0].lower() + name[1:]


def _rule_children(ctx: ParserRuleContext) -> list[ParserRuleContext]:
    return [child for child in ctx.getChildren() if isinstance(child, ParserRuleContext)]


def _children_named(ctx: ParserRuleContext, name: str) -> list[ParserRuleContext]:
    """Return descendants with the given rule name, not descending past a match."""

    found: list[ParserRuleContext] = []

    def visit(node: ParserRuleContext) -> None:
        for child in _rule_children(node):
            if _rule_name(child) == name:
                found.append(child)
            else:
                visit(child)

    visit(ctx)
    return found


def _first(ctx: ParserRuleContext, name: str) -> ParserRuleContext | None:
    matches = _children_named(ctx, name)
    return matches[0] if matches else None


def _nested_statements(statement_ctx: ParserRuleContext) -> list[ParserRuleContext]:
    """Return the statements directly nested inside a block statement."""

    nested: list[ParserRuleContext] = []

    def visit(node: ParserRuleContext) -> None:
        for child in _rule_children(node):
            if _rule_name(child) == "statement":
                nested.append(child)  # don't descend; its own children are built recursively
            else:
                visit(child)

    visit(statement_ctx)
    return nested


def _loose_paragraphs(ctx: ParserRuleContext) -> list[ParserRuleContext]:
    """Return paragraphs declared directly under a body/section's paragraph list."""

    container = next((c for c in _rule_children(ctx) if _rule_name(c) == "paragraphs"), None)
    if container is None:
        return []
    return _children_named(container, "paragraph")


def _section_names(division: ParserRuleContext) -> tuple[Section, ...]:
    sections: list[Section] = []

    def visit(node: ParserRuleContext) -> None:
        for child in _rule_children(node):
            if _rule_name(child).endswith("Section"):
                sections.append(Section(name=child.start.text.upper(), line_number=child.start.line))
            else:
                visit(child)

    visit(division)
    return tuple(sections)


def _section_header_name(section_ctx: ParserRuleContext) -> str:
    header = _first(section_ctx, "procedureSectionHeader")
    token = header.start if header is not None else section_ctx.start
    return token.text.upper()


def _division_lines(division: ParserRuleContext, source_lines: list[str]) -> tuple[str, ...]:
    start = division.start.line
    stop = (division.stop or division.start).line
    return tuple(source_lines[start - 1 : stop])


def _ctx_text(ctx: ParserRuleContext) -> str:
    start = ctx.start
    stop = ctx.stop or ctx.start
    return start.getInputStream().getText(start.start, stop.stop)
