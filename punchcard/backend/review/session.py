"""Persistence models and helpers for review rewrite sessions.

The review database is intentionally small: sessions describe a source file,
paragraphs hold mutable working state, and events form the append-only audit log.
Like a good chevruta, the current answer may change, but the discussion history
must remain available for later learning and accountability.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

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
