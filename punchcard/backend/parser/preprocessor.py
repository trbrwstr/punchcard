"""COBOL copybook preprocessor: COPY and REPLACE expansion.

This mirrors the standard COBOL preprocessing pass that runs before parsing. It
uses the vendored ANTLR ``Cobol85Preprocessor`` grammar to locate ``COPY`` and
``REPLACE`` constructs, then reconstructs an expanded source string:

* ``COPY name`` is replaced by the named copybook's text, resolved from a search
  path; ``COPY name REPLACING ==a== BY ==b==`` applies the substitutions to the
  copied text; nested ``COPY`` inside a copybook is expanded recursively (with
  cycle detection).
* ``REPLACE ==a== BY ==b==`` ... ``REPLACE OFF`` applies program-level text
  substitution to the source between the two directives.
* ``EJECT`` / ``SKIP`` / ``TITLE`` / ``CBL`` / ``PROCESS`` listing directives are
  dropped, as they are not part of the program text.

Everything the grammar does not recognize passes through verbatim (whitespace is
preserved on a hidden channel), so source without ``COPY``/``REPLACE`` is
returned unchanged. Expansion is best-effort: if the preprocessor cannot parse
the input, the original source is returned untouched.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from antlr4 import CommonTokenStream, InputStream, ParserRuleContext
from antlr4.error.ErrorListener import ErrorListener

from punchcard.backend.parser._generated.Cobol85PreprocessorLexer import Cobol85PreprocessorLexer
from punchcard.backend.parser._generated.Cobol85PreprocessorParser import Cobol85PreprocessorParser
from punchcard.backend.parser.ir import CopySpan

#: Filename suffixes tried (in order) when resolving a copybook name.
DEFAULT_COPYBOOK_EXTENSIONS: tuple[str, ...] = ("", ".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB")

_MAX_COPY_DEPTH = 50
_DROP_RULES = frozenset({"ejectStatement", "skipStatement", "titleStatement", "compilerOptions"})


def preprocess(
    source: str,
    *,
    copybook_paths: Iterable[str | Path] = (),
    extensions: Sequence[str] = DEFAULT_COPYBOOK_EXTENSIONS,
    strict: bool = False,
) -> str:
    """Expand ``COPY``/``REPLACE`` in ``source`` and return the expanded text.

    Args:
        source: COBOL source text.
        copybook_paths: Directories searched (in order) for copybooks.
        extensions: Filename suffixes tried for each copybook name.
        strict: When true, an unresolved copybook raises :class:`CopybookNotFoundError`
            instead of leaving an inline comment marker.
    """

    return expand(source, copybook_paths=copybook_paths, extensions=extensions, strict=strict).text


@dataclass(frozen=True, slots=True)
class ExpandedSource:
    """Expanded COBOL text plus the copybook provenance of its lines."""

    text: str
    copy_spans: tuple[CopySpan, ...] = field(default_factory=tuple)


def expand(
    source: str,
    *,
    copybook_paths: Iterable[str | Path] = (),
    extensions: Sequence[str] = DEFAULT_COPYBOOK_EXTENSIONS,
    strict: bool = False,
) -> ExpandedSource:
    """Expand ``COPY``/``REPLACE`` and return the text plus copybook line spans.

    The spans record which expanded-source lines came from a ``COPY`` (attributed
    to the directly-named copybook). They are reported only when no program-level
    ``REPLACE``/listing directive altered the text after copy expansion, since
    those edits would shift line numbers; in that case ``copy_spans`` is empty.
    """

    if not _has_directives(source):
        return ExpandedSource(source)

    paths = [Path(p) for p in copybook_paths]
    resolver = _CopybookResolver(paths, tuple(extensions), strict)
    after_copy, spans = _expand_copies(source, resolver, depth=0)
    final = _apply_replace_statements(after_copy)
    if final != after_copy:
        # REPLACE/listing directives shifted lines; remap spans onto the final text.
        spans = _remap_spans(spans, after_copy, final)
    return ExpandedSource(final, tuple(spans))


class CopybookNotFoundError(FileNotFoundError):
    """Raised in strict mode when a ``COPY`` target cannot be resolved."""


def _remap_spans(spans: list[CopySpan], old_text: str, new_text: str) -> list[CopySpan]:
    """Map copybook spans from ``old_text`` line numbers onto ``new_text``.

    Uses a line-level diff so spans survive the line shifts the REPLACE pass
    introduces (removed directive lines, collapsed multi-line replacements).
    Lines that the REPLACE pass changed drop out of the mapping; a span is kept
    if any of its lines still has a counterpart in the new text.
    """

    matcher = difflib.SequenceMatcher(a=old_text.splitlines(), b=new_text.splitlines(), autojunk=False)
    old_to_new: dict[int, int] = {}
    for old_start, new_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            old_to_new[old_start + offset + 1] = new_start + offset + 1

    remapped: list[CopySpan] = []
    for span in spans:
        mapped = [old_to_new[line] for line in range(span.start_line, span.end_line + 1) if line in old_to_new]
        if mapped:
            remapped.append(CopySpan(span.copybook, min(mapped), max(mapped)))
    return remapped


def _has_directives(source: str) -> bool:
    return re.search(r"\b(COPY|REPLACE)\b", source, re.IGNORECASE) is not None


class _SilentErrorListener(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e) -> None:  # noqa: N802
        return None


def _parse(source: str) -> tuple[ParserRuleContext, CommonTokenStream] | None:
    lexer = Cobol85PreprocessorLexer(InputStream(source))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_SilentErrorListener())
    tokens = CommonTokenStream(lexer)
    parser = Cobol85PreprocessorParser(tokens)
    parser.removeErrorListeners()
    parser.addErrorListener(_SilentErrorListener())
    try:
        tree = parser.startRule()
    except Exception:
        return None
    return tree, tokens


# --- COPY expansion ----------------------------------------------------------


class _CopybookResolver:
    def __init__(self, paths: list[Path], extensions: tuple[str, ...], strict: bool) -> None:
        self.paths = paths
        self.extensions = extensions
        self.strict = strict

    def resolve(self, name: str) -> Path | None:
        name = name.strip().strip("'\"")
        for directory in self.paths:
            for ext in self.extensions:
                candidate = directory / f"{name}{ext}"
                if candidate.is_file():
                    return candidate
        return None


def _expand_copies(
    source: str, resolver: _CopybookResolver, *, depth: int, seen: frozenset[Path] = frozenset()
) -> tuple[str, list[CopySpan]]:
    """Expand COPY statements, returning the text and copybook line spans.

    Each ``COPY`` interval is replaced by its (recursively expanded) copybook
    text. Lines are attributed to the *innermost* copybook they came from: a
    nested ``COPY``'s lines keep the nested copybook's name, and the enclosing
    copybook claims only its own lines.
    """

    parsed = _parse(source)
    if parsed is None:
        return source, []
    tree, _tokens = parsed

    copies = sorted(_find_all(tree, "copyStatement"), key=lambda ctx: ctx.start.start)
    if not copies:
        return source, []

    parts: list[tuple[str, list[CopySpan]]] = []
    position = 0
    for copy_ctx in copies:
        parts.append((source[position : copy_ctx.start.start], []))
        parts.append(_expand_one_copy(copy_ctx, resolver, depth=depth, seen=seen))
        position = copy_ctx.stop.stop + 1
    parts.append((source[position:], []))

    return _join_with_spans(parts)


def _join_with_spans(parts: list[tuple[str, list[CopySpan]]]) -> tuple[str, list[CopySpan]]:
    """Concatenate parts, shifting each part's relative spans to absolute lines."""

    text_parts: list[str] = []
    spans: list[CopySpan] = []
    line = 1
    for chunk, relative_spans in parts:
        if not chunk:
            continue
        for span in relative_spans:
            spans.append(CopySpan(span.copybook, line + span.start_line - 1, line + span.end_line - 1))
        text_parts.append(chunk)
        line += chunk.count("\n")
    return "".join(text_parts), spans


def _copy_name(copy_ctx: ParserRuleContext) -> str:
    return _first(copy_ctx, "copySource").getText().strip().strip("'\"").upper()


def _expand_one_copy(
    copy_ctx: ParserRuleContext, resolver: _CopybookResolver, *, depth: int, seen: frozenset[Path]
) -> tuple[str, list[CopySpan]]:
    """Expand one COPY, returning its text and spans relative to that text."""

    name = _copy_name(copy_ctx)
    clauses = _replace_clauses(copy_ctx)

    if depth >= _MAX_COPY_DEPTH:
        return _marker(f"COPY DEPTH LIMIT REACHED: {name}", name)
    path = resolver.resolve(name)
    if path is None:
        if resolver.strict:
            raise CopybookNotFoundError(name)
        return _marker(f"COPYBOOK NOT FOUND: {name}", name)
    if path in seen:
        return _marker(f"COPY CYCLE SKIPPED: {name}", name)

    body = path.read_text(encoding="utf-8")
    body, inner_spans = _expand_copies(body, resolver, depth=depth + 1, seen=seen | {path})
    if clauses:
        before = body.count("\n")
        body = _apply_clauses(body, clauses)
        if body.count("\n") != before:
            # A multi-line pseudo-text replacement moved line boundaries; the
            # inner spans no longer line up, so attribute the whole block to name.
            inner_spans = []
    if not body.endswith("\n"):
        body += "\n"
    return body, _attribute_remaining(body, inner_spans, name)


def _marker(message: str, name: str) -> tuple[str, list[CopySpan]]:
    return f"      *> {message}\n", [CopySpan(name, 1, 1)]


def _attribute_remaining(text: str, inner_spans: list[CopySpan], name: str) -> list[CopySpan]:
    """Attribute lines not covered by ``inner_spans`` to ``name``."""

    total = len(text.splitlines())
    covered = {line for span in inner_spans for line in range(span.start_line, span.end_line + 1)}
    spans = list(inner_spans)
    start: int | None = None
    for line in range(1, total + 1):
        if line not in covered:
            start = line if start is None else start
        elif start is not None:
            spans.append(CopySpan(name, start, line - 1))
            start = None
    if start is not None:
        spans.append(CopySpan(name, start, total))
    return spans


# --- REPLACE statement handling ---------------------------------------------


def _apply_replace_statements(source: str) -> str:
    parsed = _parse(source)
    if parsed is None:
        return source
    tree, _tokens = parsed

    areas = _find_all(tree, "replaceArea")
    drops = [ctx for rule in _DROP_RULES for ctx in _find_all(tree, rule)]
    if not areas and not drops:
        return source

    # Edit by character offset, right-to-left, so earlier offsets stay valid.
    edits: list[tuple[int, int, str]] = []
    for area in areas:
        edits.extend(_replace_area_edits(area))
    for ctx in drops:
        edits.append((ctx.start.start, ctx.stop.stop + 1, ""))

    result = source
    for start, stop, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        result = result[:start] + replacement + result[stop:]
    return result


def _replace_area_edits(area: ParserRuleContext) -> list[tuple[int, int, str]]:
    by_statement = _first(area, "replaceByStatement")
    off_statement = _first(area, "replaceOffStatement")
    if by_statement is None:
        return []
    clauses = _replace_clauses(by_statement)

    stream = area.start.getInputStream()
    inner_start = by_statement.stop.stop + 1
    inner_stop = off_statement.start.start if off_statement is not None else (area.stop or area.start).stop + 1
    inner = stream.getText(inner_start, inner_stop - 1)
    new_inner = _apply_clauses(inner, clauses)

    edits = [(by_statement.start.start, by_statement.stop.stop + 1, ""), (inner_start, inner_stop, new_inner)]
    if off_statement is not None:
        edits.append((off_statement.start.start, off_statement.stop.stop + 1, ""))
    return edits


# --- replacement clauses -----------------------------------------------------


def _replace_clauses(ctx: ParserRuleContext) -> list[tuple[str, str]]:
    clauses: list[tuple[str, str]] = []
    for clause in _find_all(ctx, "replaceClause"):
        # Use the raw source slice, not getText(): the latter concatenates tokens
        # without whitespace, which would collapse multi-word pseudo-text.
        able = _pseudo_inner(_ctx_source(_first(clause, "replaceable")))
        replacement = _pseudo_inner(_ctx_source(_first(clause, "replacement")))
        if able:
            clauses.append((able, replacement))
    return clauses


def _ctx_source(ctx: ParserRuleContext) -> str:
    start = ctx.start
    stop = ctx.stop or ctx.start
    return start.getInputStream().getText(start.start, stop.stop)


def _pseudo_inner(text: str) -> str:
    text = text.strip()
    if text.startswith("==") and text.endswith("=="):
        text = text[2:-2]
    return text.strip()


#: A COBOL nonnumeric literal (single- or double-quoted, with doubled-quote escapes).
_LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def _apply_clauses(text: str, clauses: Sequence[tuple[str, str]]) -> str:
    """Apply REPLACING/REPLACE clauses as pseudo-text token-sequence substitution.

    Matching is whitespace-flexible (a pseudo-text phrase matches across runs of
    whitespace and newlines), case-insensitive on COBOL words, and bounded by
    COBOL-word characters so partial words are not hit. String literals are left
    untouched, since a quoted literal is a single token a pseudo-text phrase
    cannot reach inside.
    """

    for able, replacement in clauses:
        words = able.split()
        if not words:
            continue
        pattern = re.compile(
            r"(?<![A-Za-z0-9-])" + r"\s+".join(re.escape(word) for word in words) + r"(?![A-Za-z0-9-])",
            re.IGNORECASE,
        )
        text = _sub_outside_literals(pattern, replacement, text)
    return text


def _sub_outside_literals(pattern: re.Pattern[str], replacement: str, text: str) -> str:
    chunks: list[str] = []
    position = 0
    for literal in _LITERAL_RE.finditer(text):
        chunks.append(pattern.sub(lambda _m: replacement, text[position : literal.start()]))
        chunks.append(literal.group(0))  # leave the literal verbatim
        position = literal.end()
    chunks.append(pattern.sub(lambda _m: replacement, text[position:]))
    return "".join(chunks)


# --- tree helpers ------------------------------------------------------------


def _rule_name(ctx: ParserRuleContext) -> str:
    name = type(ctx).__name__[:-7]  # strip "Context"
    return name[0].lower() + name[1:]


def _find_all(ctx: ParserRuleContext, name: str) -> list[ParserRuleContext]:
    found: list[ParserRuleContext] = []

    def visit(node: ParserRuleContext) -> None:
        for child in node.getChildren():
            if isinstance(child, ParserRuleContext):
                if _rule_name(child) == name:
                    found.append(child)
                visit(child)

    visit(ctx)
    return found


def _first(ctx: ParserRuleContext, name: str) -> ParserRuleContext | None:
    matches = _find_all(ctx, name)
    return matches[0] if matches else None
