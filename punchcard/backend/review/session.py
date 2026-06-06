"""Rewrite session state shared by API and TUI clients.

The service is deliberately small and in-memory for the first Punchcard review
workflow. Like starting with pshat before drash, it exposes one plain contract
for accepting, editing, rejecting/regenerating, and skipping paragraph rewrites.
FastAPI and the terminal UI both call this module so review decisions do not
fork into competing code paths.
"""Persistence models and helpers for review rewrite sessions.

The review database is intentionally small: sessions describe a source file,
paragraphs hold mutable working state, and events form the append-only audit log.
Like a good chevruta, the current answer may change, but the discussion history
must remain available for later learning and accountability.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from enum import StrEnum
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
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import JSON, Column, Engine, event, inspect
from sqlmodel import Field, Session, SQLModel, create_engine, select


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for consistent audit records."""

    return datetime.now(UTC)


class RewriteStatus(StrEnum):
    """Common lifecycle states for sessions and paragraph rewrites."""

    PENDING = "pending"
    TRANSLATED = "translated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RewriteAction(StrEnum):
    """Audit actions that must only ever be inserted, never edited in place."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TRANSLATED = "translated"


class ReviewDatabaseSettings(BaseSettings):
    """Configuration for the review SQLite database.

    Set ``PUNCHCARD_REVIEW_DATABASE_URL`` to override the default local file.
    SQLite is the only supported backend for this helper module today, keeping
    the MVP boring and reliable.
    """

    database_url: str = "sqlite:///./punchcard-review.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PUNCHCARD_REVIEW_",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def require_sqlite_url(cls, value: str) -> str:
        """Fail fast if configuration points at an unsupported database."""

        if not value.startswith("sqlite://"):
            raise ValueError("review database_url must be a SQLite URL")
        return value


class RewriteSession(SQLModel, table=True):
    """A COBOL rewrite review session for one source file."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    source_filename: str = Field(index=True, min_length=1)
    target_language: str = Field(index=True, min_length=1)
    status: str = Field(default=RewriteStatus.PENDING.value, index=True)
    created_timestamp: datetime = Field(default_factory=utc_now, index=True)
    updated_timestamp: datetime = Field(default_factory=utc_now, index=True)


class RewriteParagraph(SQLModel, table=True):
    """Mutable paragraph-level rewrite state inside a session."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="rewritesession.id", index=True)
    paragraph_name: str = Field(index=True, min_length=1)
    cobol_source: str
    suggested_output: str | None = None
    final_output: str | None = None
    status: str = Field(default=RewriteStatus.PENDING.value, index=True)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class RewriteEvent(SQLModel, table=True):
    """Append-only audit event for accepted, rejected, and translated rewrites."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="rewritesession.id", index=True)
    paragraph_name: str = Field(index=True, min_length=1)
    timestamp: datetime = Field(default_factory=utc_now, index=True)
    action: str = Field(index=True, min_length=1)
    cobol_source: str
    suggested_output: str | None = None
    final_output: str | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    model_used: str | None = None
    tokens_used: int | None = Field(default=None, ge=0)


@event.listens_for(Session, "before_flush")
def protect_rewrite_events(session: Session, _flush_context: Any, _instances: Any) -> None:
    """Reject in-place updates and deletes to preserve audit integrity."""

    for instance in session.dirty:
        if isinstance(instance, RewriteEvent) and session.is_modified(instance):
            raise ValueError("RewriteEvent rows are append-only and cannot be updated")

    for instance in session.deleted:
        if isinstance(instance, RewriteEvent):
            raise ValueError("RewriteEvent rows are append-only and cannot be deleted")


def get_engine(settings: ReviewDatabaseSettings | None = None) -> Engine:
    """Create a SQLite engine from pydantic-settings configuration."""

    settings = settings or ReviewDatabaseSettings()
    connect_args = {"check_same_thread": False}
    return create_engine(settings.database_url, connect_args=connect_args)


def init_db(engine: Engine | None = None) -> Engine:
    """Initialize review tables and return the engine used."""

    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    return engine


def get_db_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Yield a SQLModel session suitable for FastAPI dependencies."""

    engine = engine or init_db()
    with Session(engine) as session:
        yield session


def create_rewrite_session(
    db: Session,
    *,
    source_filename: str | Path,
    target_language: str,
    status: str = RewriteStatus.PENDING.value,
) -> RewriteSession:
    """Persist a rewrite session and return it refreshed from the database."""

    rewrite_session = RewriteSession(
        source_filename=str(source_filename),
        target_language=target_language,
        status=status,
    )
    db.add(rewrite_session)
    db.commit()
    db.refresh(rewrite_session)
    return rewrite_session


def save_rewrite_paragraph(db: Session, paragraph: RewriteParagraph) -> RewriteParagraph:
    """Insert or update paragraph working state and touch its parent session."""

    now = utc_now()
    parent = db.get(RewriteSession, paragraph.session_id)
    if parent is None:
        raise ValueError(f"unknown rewrite session: {paragraph.session_id}")

    parent.updated_timestamp = now
    db.add(paragraph)
    db.add(parent)
    db.commit()
    db.refresh(paragraph)
    return paragraph


def append_rewrite_event(
    db: Session,
    *,
    session_id: str,
    paragraph_name: str,
    action: RewriteAction | str,
    cobol_source: str,
    suggested_output: str | None = None,
    final_output: str | None = None,
    confidence_score: float | None = None,
    model_used: str | None = None,
    tokens_used: int | None = None,
) -> RewriteEvent:
    """Append an audit event for a review decision or translation.

    Only accepted, rejected, and translated actions are allowed here. The
    ``RewriteEvent`` table is additionally guarded by a flush hook so existing
    audit rows cannot be updated or deleted through SQLModel sessions.
    """

    allowed_actions = {action.value for action in RewriteAction}
    normalized_action = action.value if isinstance(action, RewriteAction) else action
    if normalized_action not in allowed_actions:
        raise ValueError(f"audit action must be one of {sorted(allowed_actions)}")

    parent = db.get(RewriteSession, session_id)
    if parent is None:
        raise ValueError(f"unknown rewrite session: {session_id}")

    event_row = RewriteEvent(
        session_id=session_id,
        paragraph_name=paragraph_name,
        action=normalized_action,
        cobol_source=cobol_source,
        suggested_output=suggested_output,
        final_output=final_output,
        confidence_score=confidence_score,
        model_used=model_used,
        tokens_used=tokens_used,
    )
    parent.updated_timestamp = event_row.timestamp
    db.add(event_row)
    db.add(parent)
    db.commit()
    db.refresh(event_row)
    return event_row


def list_rewrite_events(db: Session, session_id: str) -> Sequence[RewriteEvent]:
    """Return audit events for a session in chronological insertion order."""

    statement = (
        select(RewriteEvent)
        .where(RewriteEvent.session_id == session_id)
        .order_by(RewriteEvent.timestamp, RewriteEvent.id)
    )
    return db.exec(statement).all()


def database_tables_exist(engine: Engine) -> bool:
    """Return whether all review tables already exist in the configured DB."""

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    expected = {
        RewriteSession.__tablename__,
        RewriteParagraph.__tablename__,
        RewriteEvent.__tablename__,
    }
    return expected.issubset(existing)
