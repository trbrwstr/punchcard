"""FastAPI session endpoints for Punchcard."""

from __future__ import annotations

from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from punchcard.backend.llm.prompts import render_translation_prompt
from punchcard.backend.parser import parse_cobol
from punchcard.backend.review.confidence import score_program_confidence
from punchcard.backend.review.export import ReviewSession, export_session


class Translator(Protocol):
    """Protocol for injectable translation services."""

    async def translate(self, prompt: str) -> str:
        """Translate a rendered prompt."""


class CreateSessionRequest(BaseModel):
    """Payload for creating a review session."""

    source: str = Field(min_length=1)


class SessionResponse(BaseModel):
    """Public session summary."""

    id: str
    program_id: str | None
    confidence: float
    statements: int


class TranslationResponse(BaseModel):
    """Translation endpoint response."""

    session_id: str
    translation: str


SessionStore = dict[str, ReviewSession]


def create_app(
    *,
    translator: Translator | None = None,
    store: SessionStore | None = None,
) -> FastAPI:
    """Create the API app with injectable state and LLM boundary."""

    app = FastAPI(title="Punchcard")
    session_store: SessionStore = store if store is not None else {}
    app.state.sessions = session_store

    async def get_translator() -> Translator:
        if translator is None:
            from punchcard.backend.llm.anthropic_client import AnthropicTranslator

            return AnthropicTranslator()
        return translator

    @app.post("/sessions", response_model=SessionResponse, status_code=201)
    async def create_session(payload: CreateSessionRequest) -> SessionResponse:
        program = parse_cobol(payload.source)
        confidence = score_program_confidence(program)
        session = ReviewSession(source=payload.source, program=program, confidence=confidence)
        session.record("session.created", "Parsed COBOL source and computed confidence.")
        session_store[session.id] = session
        return _session_response(session)

    @app.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        return _session_response(_lookup_session(session_store, session_id))

    @app.post("/sessions/{session_id}/translate", response_model=TranslationResponse)
    async def translate_session(
        session_id: str,
        service: Translator = Depends(get_translator),
    ) -> TranslationResponse:
        session = _lookup_session(session_store, session_id)
        prompt = render_translation_prompt(session.program, session.confidence)
        session.translation = await service.translate(prompt)
        session.record("translation.completed", "Rendered prompt and stored mocked or injected translation.")
        return TranslationResponse(session_id=session.id, translation=session.translation)

    @app.get("/sessions/{session_id}/export")
    async def export_review_session(session_id: str) -> dict[str, object]:
        session = _lookup_session(session_store, session_id)
        session.record("session.exported", "Exported review result and audit log.")
        return export_session(session)

    return app


def _lookup_session(store: SessionStore, session_id: str) -> ReviewSession:
    try:
        return store[session_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


def _session_response(session: ReviewSession) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        program_id=session.program.program_id,
        confidence=session.confidence.score,
        statements=len(session.program.all_statements),
    )


app = create_app()
