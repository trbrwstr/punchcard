"""Rewrite session state shared by API and TUI clients.

The service is deliberately small and in-memory for the first Punchcard review
workflow. Like starting with pshat before drash, it exposes one plain contract
for accepting, editing, rejecting/regenerating, and skipping paragraph rewrites.
FastAPI and the terminal UI both call this module so review decisions do not
fork into competing code paths.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from punchcard.backend.parser import parse_cobol
from punchcard.backend.parser.ir import Paragraph, Statement


@dataclass(slots=True)
class RewriteItem:
    """One COBOL paragraph and its proposed translation."""

    id: str
    paragraph_name: str
    original: str
    suggested_translation: str
    unified_diff: str
    confidence_score: float
    risk_flags: list[str] = field(default_factory=list)
    status: str = "pending"
    regeneration_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for API/TUI adapters."""

        return {
            "id": self.id,
            "paragraph_name": self.paragraph_name,
            "original": self.original,
            "suggested_translation": self.suggested_translation,
            "unified_diff": self.unified_diff,
            "confidence_score": self.confidence_score,
            "risk_flags": list(self.risk_flags),
            "status": self.status,
            "regeneration_count": self.regeneration_count,
        }


@dataclass(slots=True)
class RewriteSession:
    """A keyboard-review session over proposed paragraph rewrites."""

    id: str
    items: list[RewriteItem]
    cursor: int = 0

    @property
    def current_item(self) -> RewriteItem | None:
        """Return the next pending item, or ``None`` when review is complete."""

        while self.cursor < len(self.items) and self.items[self.cursor].status != "pending":
            self.cursor += 1
        if self.cursor >= len(self.items):
            return None
        return self.items[self.cursor]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable session snapshot."""

        return {
            "id": self.id,
            "cursor": self.cursor,
            "items": [item.to_dict() for item in self.items],
        }


class RewriteSessionService:
    """Owns rewrite sessions for both FastAPI and the Textual app."""

    def __init__(self) -> None:
        self._sessions: dict[str, RewriteSession] = {}

    def create_from_cobol(self, source: str, *, session_id: str | None = None) -> RewriteSession:
        """Parse COBOL source and create a review session from its paragraphs."""

        program = parse_cobol(source)
        paragraphs = list(program.procedure.paragraphs)
        for section in program.procedure.sections:
            paragraphs.extend(section.paragraphs)

        items = [_item_from_paragraph(paragraph) for paragraph in paragraphs]
        if not items and program.all_statements:
            synthetic = Paragraph(name="PROCEDURE", line_number=1, statements=tuple(program.all_statements))
            items.append(_item_from_paragraph(synthetic))

        session = RewriteSession(id=session_id or uuid4().hex, items=items)
        self._sessions[session.id] = session
        return session

    def load_json(self, path: Path) -> RewriteSession:
        """Load a session from a simple JSON file.

        The loader accepts either a complete session object with ``items`` or a
        seed file with ``source`` containing COBOL text. This keeps the TUI easy
        to start during early product discovery.
        """

        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "source" in payload:
            return self.create_from_cobol(str(payload["source"]), session_id=payload.get("id"))
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("session JSON must contain either 'source' or an 'items' list")

        items = [_item_from_mapping(raw_item) for raw_item in payload["items"]]
        session = RewriteSession(id=str(payload.get("id") or uuid4().hex), items=items, cursor=int(payload.get("cursor", 0)))
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> RewriteSession:
        """Return an existing session or raise ``KeyError``."""

        return self._sessions[session_id]

    def current_item(self, session_id: str) -> RewriteItem | None:
        """Return the current item for a session."""

        return self.get(session_id).current_item

    def accept(self, session_id: str, *, edited_translation: str | None = None) -> RewriteItem:
        """Accept the current item, optionally storing an edited translation."""

        item = self._require_current(session_id)
        if edited_translation is not None:
            _replace_translation(item, edited_translation)
        item.status = "accepted"
        self.get(session_id).cursor += 1
        return item

    def edit(self, session_id: str, edited_translation: str) -> RewriteItem:
        """Save an edited translation without accepting it yet."""

        item = self._require_current(session_id)
        _replace_translation(item, edited_translation)
        return item

    def reject_and_regenerate(self, session_id: str) -> RewriteItem:
        """Reject the current proposal and generate a fresh simple alternative."""

        item = self._require_current(session_id)
        item.regeneration_count += 1
        item.suggested_translation = _regenerated_translation(item)
        item.unified_diff = _unified_diff(item.original, item.suggested_translation)
        item.confidence_score = max(0.1, item.confidence_score - 0.05)
        item.status = "pending"
        return item

    def skip(self, session_id: str) -> RewriteItem:
        """Skip the current item and advance to the next paragraph."""

        item = self._require_current(session_id)
        item.status = "skipped"
        self.get(session_id).cursor += 1
        return item

    def _require_current(self, session_id: str) -> RewriteItem:
        item = self.current_item(session_id)
        if item is None:
            raise IndexError("session has no pending rewrite items")
        return item


def _item_from_mapping(raw_item: dict[str, Any]) -> RewriteItem:
    original = str(raw_item.get("original", ""))
    suggestion = str(raw_item.get("suggested_translation", ""))
    return RewriteItem(
        id=str(raw_item.get("id") or uuid4().hex),
        paragraph_name=str(raw_item.get("paragraph_name") or "PARAGRAPH"),
        original=original,
        suggested_translation=suggestion,
        unified_diff=str(raw_item.get("unified_diff") or _unified_diff(original, suggestion)),
        confidence_score=float(raw_item.get("confidence_score", 0.5)),
        risk_flags=[str(flag) for flag in raw_item.get("risk_flags", [])],
        status=str(raw_item.get("status", "pending")),
        regeneration_count=int(raw_item.get("regeneration_count", 0)),
    )


def _item_from_paragraph(paragraph: Paragraph) -> RewriteItem:
    original = _paragraph_source(paragraph)
    suggestion = _suggest_translation(paragraph.statements)
    return RewriteItem(
        id=f"{paragraph.name.lower()}-{paragraph.line_number}",
        paragraph_name=paragraph.name,
        original=original,
        suggested_translation=suggestion,
        unified_diff=_unified_diff(original, suggestion),
        confidence_score=_confidence(paragraph.statements),
        risk_flags=_risk_flags(paragraph.statements),
    )


def _paragraph_source(paragraph: Paragraph) -> str:
    lines = [f"{paragraph.name}."]
    lines.extend(f"    {statement.text}." for statement in paragraph.statements)
    return "\n".join(lines)


def _suggest_translation(statements: tuple[Statement, ...]) -> str:
    translated = ["# Suggested Python translation; review before shipping."]
    for statement in statements:
        if statement.verb == "DISPLAY":
            translated.append(f"print({_display_argument(statement)!r})")
        elif statement.verb == "MOVE" and len(statement.tokens) >= 4 and statement.tokens[-2] == "TO":
            translated.append(f"{statement.tokens[-1].lower().replace('-', '_')} = {statement.tokens[1]!r}")
        elif statement.verb == "STOP":
            translated.append("return")
        else:
            translated.append(f"# TODO: translate COBOL statement: {statement.text}")
    return "\n".join(translated)


def _regenerated_translation(item: RewriteItem) -> str:
    return "\n".join(
        [
            "# Regenerated translation; compare carefully before accepting.",
            f"# Paragraph: {item.paragraph_name}",
            "# Keep business semantics first, syntax second.",
            item.suggested_translation,
        ]
    )


def _display_argument(statement: Statement) -> str:
    text = statement.text.removeprefix("DISPLAY").strip()
    return text.strip("'") or ""


def _risk_flags(statements: tuple[Statement, ...]) -> list[str]:
    flags: list[str] = []
    verbs = {statement.verb for statement in statements}
    if "CALL" in verbs:
        flags.append("external-call")
    if {"READ", "WRITE"} & verbs:
        flags.append("file-io")
    if "PERFORM" in verbs:
        flags.append("control-flow")
    if any(statement.verb not in {"DISPLAY", "MOVE", "STOP"} for statement in statements):
        flags.append("manual-review")
    return flags


def _confidence(statements: tuple[Statement, ...]) -> float:
    if not statements:
        return 0.4
    supported = sum(statement.verb in {"DISPLAY", "MOVE", "STOP"} for statement in statements)
    return round(0.35 + (supported / len(statements)) * 0.55, 2)


def _replace_translation(item: RewriteItem, edited_translation: str) -> None:
    item.suggested_translation = edited_translation
    item.unified_diff = _unified_diff(item.original, edited_translation)


def _unified_diff(original: str, suggestion: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            suggestion.splitlines(),
            fromfile="original.cbl",
            tofile="suggested.py",
            lineterm="",
        )
    )


session_service = RewriteSessionService()
