"""FastAPI adapters for Punchcard."""

from punchcard.backend.api.sessions import create_app

__all__ = ["create_app"]
"""FastAPI adapters for Punchcard rewrite sessions."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from punchcard.backend.review import RewriteSessionService, session_service


class CreateSessionRequest(BaseModel):
    """Request body for creating a rewrite session from COBOL source."""

    source: str = Field(min_length=1)
    session_id: str | None = None


class EditRequest(BaseModel):
    """Request body for editing a suggested translation."""

    suggested_translation: str = Field(min_length=1)


def create_app(service: RewriteSessionService | None = None) -> FastAPI:
    """Build the FastAPI app around the shared rewrite session service."""

    app = FastAPI(title="Punchcard")
    active_service = service or session_service

    def get_service() -> RewriteSessionService:
        return active_service

    @app.post("/sessions")
    def create_session(
        payload: CreateSessionRequest,
        service: RewriteSessionService = Depends(get_service),
    ) -> dict:
        session = service.create_from_cobol(payload.source, session_id=payload.session_id)
        return session.to_dict()

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str, service: RewriteSessionService = Depends(get_service)) -> dict:
        try:
            return service.get(session_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.get("/sessions/{session_id}/current")
    def current_item(
        session_id: str,
        service: RewriteSessionService = Depends(get_service),
    ) -> dict | None:
        try:
            item = service.current_item(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        return None if item is None else item.to_dict()

    @app.post("/sessions/{session_id}/accept")
    def accept(
        session_id: str,
        service: RewriteSessionService = Depends(get_service),
        payload: EditRequest | None = None,
    ) -> dict:
        try:
            item = service.accept(
                session_id,
                edited_translation=None if payload is None else payload.suggested_translation,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except IndexError as exc:
            raise HTTPException(status_code=409, detail="session has no pending items") from exc
        return item.to_dict()

    @app.post("/sessions/{session_id}/edit")
    def edit(
        session_id: str,
        payload: EditRequest,
        service: RewriteSessionService = Depends(get_service),
    ) -> dict:
        try:
            return service.edit(session_id, payload.suggested_translation).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except IndexError as exc:
            raise HTTPException(status_code=409, detail="session has no pending items") from exc

    @app.post("/sessions/{session_id}/reject")
    def reject(session_id: str, service: RewriteSessionService = Depends(get_service)) -> dict:
        try:
            return service.reject_and_regenerate(session_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except IndexError as exc:
            raise HTTPException(status_code=409, detail="session has no pending items") from exc

    @app.post("/sessions/{session_id}/skip")
    def skip(session_id: str, service: RewriteSessionService = Depends(get_service)) -> dict:
        try:
            return service.skip(session_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except IndexError as exc:
            raise HTTPException(status_code=409, detail="session has no pending items") from exc

    return app


app = create_app()

__all__ = ["app", "create_app", "CreateSessionRequest", "EditRequest"]
