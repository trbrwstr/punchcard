"""FastAPI routes for rewrite sessions.

This module is the HTTP boundary for Punchcard. It keeps request/response models
explicit, stores only small MVP session state in SQLite, and never returns raw
SQLModel rows. Nu, like good chavruta discipline: expose the argument, not the
messy notebook underneath.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, Text
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

from punchcard.backend.llm import get_llm_client
from punchcard.backend.llm.confidence import score_paragraph
from punchcard.backend.parser.cobol_listener import parse_cobol
from punchcard.backend.parser.ir import CobolProgram, DataDiv, Paragraph

ALLOWED_EXTENSIONS = {".cbl", ".cob"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
DEFAULT_DATABASE_URL = "sqlite:///./punchcard.sqlite3"

#: Supported translation targets and the file extension each exports to.
LANGUAGE_EXTENSIONS = {"python": ".py", "java": ".java"}
COMMENT_PREFIXES = {"python": "#", "java": "//"}
DEFAULT_TARGET_LANGUAGE = "python"
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILENAME_LENGTH = 120


def _normalize_language(language: str) -> str:
    """Normalize a requested target language to a supported value."""

    normalized = (language or "").strip().lower()
    return normalized if normalized in LANGUAGE_EXTENSIONS else DEFAULT_TARGET_LANGUAGE


router = APIRouter()
_engine = None


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class RewriteSession(SQLModel, table=True):
    """Internal persisted rewrite session."""

    id: str = SQLField(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    filename: str
    program_id: str | None = None
    target_language: str = "python"
    status: str = "READY"
    source: str = SQLField(sa_column=Column(Text, nullable=False))
    ir_json: str = SQLField(sa_column=Column(Text, nullable=False))
    created_at: datetime = SQLField(default_factory=_utcnow)
    updated_at: datetime = SQLField(default_factory=_utcnow)


class ParagraphRewrite(SQLModel, table=True):
    """Internal rewrite state for a single COBOL paragraph."""

    id: str = SQLField(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = SQLField(index=True)
    name: str = SQLField(index=True)
    source: str = SQLField(sa_column=Column(Text, nullable=False))
    status: str = "PENDING"
    confidence_score: float | None = None
    risk_flags_json: str = "[]"
    translated_text: str | None = SQLField(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = SQLField(default_factory=_utcnow)
    updated_at: datetime = SQLField(default_factory=_utcnow)


class AuditEvent(SQLModel, table=True):
    """Internal append-only audit event."""

    id: str = SQLField(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = SQLField(index=True)
    paragraph_name: str | None = SQLField(default=None, index=True)
    event_type: str = SQLField(index=True)
    detail_json: str = "{}"
    created_at: datetime = SQLField(default_factory=_utcnow)


class SessionCreateResponse(BaseModel):
    """Response returned after a source upload creates a session."""

    id: str
    filename: str
    program_id: str | None
    target_language: str
    status: str
    progress: float = Field(ge=0, le=1)
    paragraph_count: int


class SessionStatusResponse(BaseModel):
    """Public status summary for one rewrite session."""

    id: str
    filename: str
    program_id: str | None
    target_language: str
    status: str
    progress: float = Field(ge=0, le=1)
    paragraph_count: int
    translated_count: int
    accepted_count: int
    rejected_count: int
    created_at: datetime
    updated_at: datetime


class ParagraphResponse(BaseModel):
    """Public paragraph rewrite summary."""

    name: str
    status: str
    confidence_score: float | None
    risk_flags: list[str]


class ParagraphListResponse(BaseModel):
    """Public collection wrapper for paragraph summaries."""

    session_id: str
    paragraphs: list[ParagraphResponse]


class ParagraphDetailResponse(BaseModel):
    """Public paragraph detail including source and any translation."""

    name: str
    status: str
    confidence_score: float | None
    risk_flags: list[str]
    source: str
    translated_text: str | None


class TranslationResponse(BaseModel):
    """Public response after translation is requested."""

    session_id: str
    paragraph_name: str
    status: str
    translated_text: str
    confidence_score: float
    risk_flags: list[str]


class ParagraphDecisionResponse(BaseModel):
    """Public response after accept/reject review actions."""

    session_id: str
    paragraph_name: str
    status: str
    audit_event_type: str


class AuditEventResponse(BaseModel):
    """Public audit event shape used by export."""

    event_type: str
    paragraph_name: str | None
    detail: dict[str, Any]
    created_at: datetime


class ExportResponse(BaseModel):
    """Translated output plus JSON-ready audit log."""

    session_id: str
    filename: str
    translated_output: str
    audit_log: list[AuditEventResponse]


class ErrorResponse(BaseModel):
    """Documented error payload."""

    detail: str


@router.post(
    "/sessions",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
)
def create_session(
    file: Annotated[UploadFile, File(description="A COBOL source file ending in .cbl or .cob")],
    db: Annotated[Session, Depends(get_db)],
    target_language: Annotated[str, Form()] = "python",
) -> SessionCreateResponse:
    """Upload COBOL, parse it into IR, and persist a rewrite session."""

    _validate_upload_name(file.filename)
    content = _read_upload_text(file)
    program = parse_cobol(content)
    session = RewriteSession(
        filename=_safe_upload_filename(file.filename),
        program_id=program.program_id,
        target_language=_normalize_language(target_language),
        source=content,
        ir_json=json.dumps(asdict(program)),
    )
    db.add(session)
    db.flush()

    paragraphs = [
        ParagraphRewrite(
            session_id=session.id,
            name=name,
            source=source,
            confidence_score=confidence,
            risk_flags_json=json.dumps(risk_flags),
        )
        for name, source, confidence, risk_flags in _paragraph_payloads(program)
    ]
    for paragraph in paragraphs:
        db.add(paragraph)
    _add_audit_event(
        db,
        session.id,
        "CREATED",
        detail={"filename": session.filename, "paragraph_count": len(paragraphs)},
    )
    db.commit()
    db.refresh(session)

    return SessionCreateResponse(
        id=session.id,
        filename=session.filename,
        program_id=session.program_id,
        target_language=session.target_language,
        status=session.status,
        progress=0.0,
        paragraph_count=len(paragraphs),
    )


@router.get("/sessions/{session_id}", response_model=SessionStatusResponse, responses={404: {"model": ErrorResponse}})
def get_session(session_id: str, db: Annotated[Session, Depends(get_db)]) -> SessionStatusResponse:
    """Return session status and progress."""

    session = _get_session_or_404(db, session_id)
    paragraphs = list(_session_paragraphs(db, session_id))
    return _session_status_response(session, paragraphs)


@router.get(
    "/sessions/{session_id}/paragraphs",
    response_model=ParagraphListResponse,
    responses={404: {"model": ErrorResponse}},
)
def list_paragraphs(session_id: str, db: Annotated[Session, Depends(get_db)]) -> ParagraphListResponse:
    """Return public paragraph review state for a session."""

    _get_session_or_404(db, session_id)
    paragraphs = [
        ParagraphResponse(
            name=paragraph.name,
            status=paragraph.status,
            confidence_score=paragraph.confidence_score,
            risk_flags=_json_list(paragraph.risk_flags_json),
        )
        for paragraph in _session_paragraphs(db, session_id)
    ]
    return ParagraphListResponse(session_id=session_id, paragraphs=paragraphs)


@router.get(
    "/sessions/{session_id}/paragraphs/{name}",
    response_model=ParagraphDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_paragraph(session_id: str, name: str, db: Annotated[Session, Depends(get_db)]) -> ParagraphDetailResponse:
    """Return one paragraph's source, status, score, risk flags, and translation."""

    _get_session_or_404(db, session_id)
    paragraph = _get_paragraph_or_404(db, session_id, name)
    return ParagraphDetailResponse(
        name=paragraph.name,
        status=paragraph.status,
        confidence_score=paragraph.confidence_score,
        risk_flags=_json_list(paragraph.risk_flags_json),
        source=paragraph.source,
        translated_text=paragraph.translated_text,
    )


@router.post(
    "/sessions/{session_id}/paragraphs/{name}/translate",
    response_model=TranslationResponse,
    responses={404: {"model": ErrorResponse}},
)
def translate_paragraph(session_id: str, name: str, db: Annotated[Session, Depends(get_db)]) -> TranslationResponse:
    """Translate one paragraph through the configured LLM abstraction."""

    session = _get_session_or_404(db, session_id)
    paragraph = _get_paragraph_or_404(db, session_id, name)
    client = get_llm_client(target_language=session.target_language)
    result = client.translate_paragraph(name=paragraph.name, source=paragraph.source)
    merged_risks = sorted(set(_json_list(paragraph.risk_flags_json)).union(result.risk_flags))
    # Confidence is the structural score computed at session creation; the
    # translator may add risk flags but does not move the heuristic score.
    confidence = paragraph.confidence_score if paragraph.confidence_score is not None else 0.0

    paragraph.translated_text = result.translated_text
    paragraph.risk_flags_json = json.dumps(merged_risks)
    paragraph.status = "TRANSLATED"
    paragraph.updated_at = _utcnow()
    _touch_session(db, session_id)
    _add_audit_event(
        db,
        session_id,
        "TRANSLATED",
        paragraph_name=paragraph.name,
        detail={"confidence_score": confidence, "risk_flags": merged_risks},
    )
    db.add(paragraph)
    db.commit()

    return TranslationResponse(
        session_id=session_id,
        paragraph_name=paragraph.name,
        status=paragraph.status,
        translated_text=result.translated_text,
        confidence_score=confidence,
        risk_flags=merged_risks,
    )


@router.post(
    "/sessions/{session_id}/paragraphs/{name}/accept",
    response_model=ParagraphDecisionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def accept_paragraph(session_id: str, name: str, db: Annotated[Session, Depends(get_db)]) -> ParagraphDecisionResponse:
    """Accept a paragraph rewrite and log an ACCEPTED audit event."""

    return _record_decision(db, session_id, name, decision_status="ACCEPTED")


@router.post(
    "/sessions/{session_id}/paragraphs/{name}/reject",
    response_model=ParagraphDecisionResponse,
    responses={404: {"model": ErrorResponse}},
)
def reject_paragraph(session_id: str, name: str, db: Annotated[Session, Depends(get_db)]) -> ParagraphDecisionResponse:
    """Reject a paragraph rewrite and log a REJECTED audit event."""

    return _record_decision(db, session_id, name, decision_status="REJECTED")


@router.get("/sessions/{session_id}/export", response_model=ExportResponse, responses={404: {"model": ErrorResponse}})
def export_session(session_id: str, db: Annotated[Session, Depends(get_db)]) -> ExportResponse:
    """Return translated output and the JSON audit log."""

    session = _get_session_or_404(db, session_id)
    paragraphs = list(_session_paragraphs(db, session_id))
    events = list(
        db.exec(select(AuditEvent).where(AuditEvent.session_id == session_id).order_by(AuditEvent.created_at))
    )
    return ExportResponse(
        session_id=session.id,
        filename=session.filename,
        translated_output="\n\n".join(
            _export_text(paragraph, target_language=session.target_language) for paragraph in paragraphs
        ),
        audit_log=[
            AuditEventResponse(
                event_type=event.event_type,
                paragraph_name=event.paragraph_name,
                detail=_json_dict(event.detail_json),
                created_at=event.created_at,
            )
            for event in events
        ],
    )


@router.get(
    "/sessions/{session_id}/export/file",
    response_class=PlainTextResponse,
    responses={404: {"model": ErrorResponse}},
)
def export_session_file(session_id: str, db: Annotated[Session, Depends(get_db)]) -> PlainTextResponse:
    """Return the assembled translated module as a single downloadable file."""

    session = _get_session_or_404(db, session_id)
    paragraphs = list(_session_paragraphs(db, session_id))
    filename = _module_filename(session.filename, session.target_language)
    return PlainTextResponse(
        content=_assemble_module(session.filename, paragraphs, target_language=session.target_language),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def init_db() -> None:
    """Create SQLite tables for the API layer."""

    SQLModel.metadata.create_all(get_engine())


def get_engine():  # type: ignore[no-untyped-def]
    """Return the process-wide SQLModel engine."""

    global _engine
    if _engine is None:
        database_url = os.getenv("PUNCHCARD_DATABASE_URL", DEFAULT_DATABASE_URL)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        _engine = create_engine(database_url, connect_args=connect_args)
    return _engine


def get_db() -> Iterable[Session]:
    """Yield a database session for FastAPI dependency injection."""

    with Session(get_engine()) as session:
        yield session


def _validate_upload_name(filename: str | None) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload must be a .cbl or .cob file.")


def _safe_upload_filename(filename: str | None) -> str:
    """Return a basename safe for storage, generated code comments, and headers."""

    original = Path(filename or "upload.cbl").name
    suffix = Path(original).suffix.lower()
    stem = Path(original).stem
    safe_stem = SAFE_FILENAME_PATTERN.sub("_", stem).strip("._-") or "upload"
    safe_stem = safe_stem[:MAX_FILENAME_LENGTH].rstrip("._-") or "upload"
    return f"{safe_stem}{suffix}"


def _read_upload_text(file: UploadFile) -> str:
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload is too large for the MVP limit.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload must be UTF-8 encoded text.",
        ) from exc


def _paragraph_payloads(program: CobolProgram) -> list[tuple[str, str, float, list[str]]]:
    seen: dict[str, int] = {}
    payloads: list[tuple[str, str, float, list[str]]] = []
    for paragraph in _iter_ir_paragraphs(program):
        name = _unique_name(paragraph.name, seen)
        source = "\n".join(statement.text for statement in paragraph.statements)
        confidence, risk_flags = _score(paragraph, program.data)
        payloads.append((name, source, confidence, risk_flags))

    if payloads:
        return payloads

    synthetic = Paragraph(name="PROGRAM", line_number=1, statements=tuple(program.all_statements))
    source = "\n".join(statement.text for statement in program.all_statements).strip() or program.source.strip()
    confidence, risk_flags = _score(synthetic, program.data)
    if not program.all_statements:
        risk_flags = sorted({*risk_flags, "NO_PARAGRAPHS"})
    return [("PROGRAM", source, confidence, risk_flags)]


def _iter_ir_paragraphs(program: CobolProgram) -> Iterable[Paragraph]:
    yield from program.procedure.paragraphs
    for section in program.procedure.sections:
        yield from section.paragraphs


def _unique_name(name: str, seen: dict[str, int]) -> str:
    count = seen.get(name, 0) + 1
    seen[name] = count
    return name if count == 1 else f"{name}-{count}"


def _score(paragraph: Paragraph, data_div: DataDiv) -> tuple[float, list[str]]:
    """Score a paragraph and return its confidence plus deduplicated risk flags.

    ``score_paragraph`` emits one flag per offending statement (so two ``GO TO``s
    yield two ``GO_TO`` flags); the API surfaces a stable, order-preserving,
    deduplicated set.
    """

    result = score_paragraph(paragraph, data_div)
    deduped = list(dict.fromkeys(result.risk_flags))
    return result.score, deduped


def _get_session_or_404(db: Session, session_id: str) -> RewriteSession:
    session = db.get(RewriteSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


def _get_paragraph_or_404(db: Session, session_id: str, name: str) -> ParagraphRewrite:
    statement = select(ParagraphRewrite).where(ParagraphRewrite.session_id == session_id, ParagraphRewrite.name == name)
    paragraph = db.exec(statement).first()
    if paragraph is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paragraph not found.")
    return paragraph


def _session_paragraphs(db: Session, session_id: str):
    return db.exec(
        select(ParagraphRewrite).where(ParagraphRewrite.session_id == session_id).order_by(ParagraphRewrite.created_at)
    )


def _record_decision(db: Session, session_id: str, name: str, *, decision_status: str) -> ParagraphDecisionResponse:
    _get_session_or_404(db, session_id)
    paragraph = _get_paragraph_or_404(db, session_id, name)
    if decision_status == "ACCEPTED" and not paragraph.translated_text:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Paragraph must be translated before it can be accepted.",
        )

    paragraph.status = decision_status
    paragraph.updated_at = _utcnow()
    _touch_session(db, session_id)
    _add_audit_event(db, session_id, decision_status, paragraph_name=paragraph.name)
    db.add(paragraph)
    db.commit()
    return ParagraphDecisionResponse(
        session_id=session_id,
        paragraph_name=paragraph.name,
        status=paragraph.status,
        audit_event_type=decision_status,
    )


def _session_status_response(session: RewriteSession, paragraphs: list[ParagraphRewrite]) -> SessionStatusResponse:
    translated = sum(1 for paragraph in paragraphs if paragraph.status in {"TRANSLATED", "ACCEPTED"})
    accepted = sum(1 for paragraph in paragraphs if paragraph.status == "ACCEPTED")
    rejected = sum(1 for paragraph in paragraphs if paragraph.status == "REJECTED")
    progress = _progress(paragraphs)
    status_value = "COMPLETED" if paragraphs and accepted + rejected == len(paragraphs) else session.status
    return SessionStatusResponse(
        id=session.id,
        filename=session.filename,
        program_id=session.program_id,
        target_language=session.target_language,
        status=status_value,
        progress=progress,
        paragraph_count=len(paragraphs),
        translated_count=translated,
        accepted_count=accepted,
        rejected_count=rejected,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _progress(paragraphs: list[ParagraphRewrite]) -> float:
    if not paragraphs:
        return 1.0
    finished = sum(1 for paragraph in paragraphs if paragraph.status in {"ACCEPTED", "REJECTED"})
    translated = sum(1 for paragraph in paragraphs if paragraph.status == "TRANSLATED")
    return round((finished + translated * 0.5) / len(paragraphs), 2)


def _export_text(paragraph: ParagraphRewrite, *, target_language: str = DEFAULT_TARGET_LANGUAGE) -> str:
    comment = _comment_prefix(target_language)
    header = f"{comment} Paragraph: {paragraph.name} [{paragraph.status}]"
    body = (
        paragraph.translated_text
        if paragraph.translated_text
        else "\n".join([f"{comment} Untranslated COBOL", *_comment_lines(paragraph.source, comment)])
    )
    return f"{header}\n{body}"


def _module_filename(source_filename: str, target_language: str = DEFAULT_TARGET_LANGUAGE) -> str:
    """Derive the exported module filename from the upload name and target language."""

    stem = SAFE_FILENAME_PATTERN.sub("_", Path(source_filename).stem).strip("._-") or "translation"
    extension = LANGUAGE_EXTENSIONS.get(target_language, LANGUAGE_EXTENSIONS[DEFAULT_TARGET_LANGUAGE])
    return f"{stem}{extension}"


def _assemble_module(
    source_filename: str,
    paragraphs: list[ParagraphRewrite],
    *,
    target_language: str = DEFAULT_TARGET_LANGUAGE,
) -> str:
    """Assemble a single reviewable module from a session's paragraphs.

    Translated paragraphs are emitted as code; anything still untranslated is
    kept as commented COBOL so the output is always a valid, auditable artifact.
    """

    comment = _comment_prefix(target_language)
    lines = [
        f"{comment} Translated from {source_filename} by Punchcard.",
        f"{comment} Review every paragraph before shipping. Paragraphs that were not",
        f"{comment} translated are preserved below as commented COBOL source.",
        "",
    ]
    for paragraph in paragraphs:
        lines.append(f"{comment} --- {paragraph.name} [{paragraph.status}] ---")
        if paragraph.translated_text:
            lines.append(paragraph.translated_text.rstrip())
        else:
            lines.append(f"{comment} Untranslated COBOL paragraph {paragraph.name}:")
            lines.extend(_comment_lines(paragraph.source, comment))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _comment_prefix(target_language: str) -> str:
    return COMMENT_PREFIXES.get(target_language, COMMENT_PREFIXES[DEFAULT_TARGET_LANGUAGE])


def _comment_lines(text: str, comment: str) -> list[str]:
    return [f"{comment} {line}" for line in text.splitlines()]


def _add_audit_event(
    db: Session,
    session_id: str,
    event_type: str,
    *,
    paragraph_name: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            session_id=session_id,
            paragraph_name=paragraph_name,
            event_type=event_type,
            detail_json=json.dumps(detail or {}),
        )
    )


def _touch_session(db: Session, session_id: str) -> None:
    session = db.get(RewriteSession, session_id)
    if session:
        session.updated_at = _utcnow()
        db.add(session)


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_dict(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
