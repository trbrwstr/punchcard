"""Export helpers and tiny audit trail models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from punchcard.backend.parser.ir import CobolProgram
from punchcard.backend.review.confidence import ConfidenceScore


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One auditable session event."""

    action: str
    detail: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class ReviewSession:
    """In-memory review session for API and tests."""

    source: str
    program: CobolProgram
    confidence: ConfidenceScore
    id: str = field(default_factory=lambda: uuid4().hex)
    translation: str | None = None
    audit_log: list[AuditEvent] = field(default_factory=list)

    def record(self, action: str, detail: str) -> None:
        """Append an audit event."""

        self.audit_log.append(AuditEvent(action=action, detail=detail))


def export_session(session: ReviewSession) -> dict[str, object]:
    """Export review output plus audit data as JSON-serializable content."""

    return {
        "session_id": session.id,
        "program_id": session.program.program_id,
        "confidence": session.confidence.score,
        "translation": session.translation,
        "audit_log": [
            {
                "action": event.action,
                "detail": event.detail,
                "created_at": event.created_at.isoformat(),
            }
            for event in session.audit_log
        ],
    }
