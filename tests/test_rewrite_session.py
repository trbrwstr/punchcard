from argparse import Namespace
import json
from pathlib import Path

from fastapi.testclient import TestClient

from punchcard.backend.api import create_app
from punchcard.backend.review import RewriteSessionService
from punchcard.tui.app import build_session


SOURCE = Path("fixtures/hello.cbl").read_text(encoding="utf-8")


def test_session_service_reviews_paragraph_actions() -> None:
    service = RewriteSessionService()
    session = service.create_from_cobol(SOURCE, session_id="demo")

    item = service.current_item(session.id)

    assert item is not None
    assert item.paragraph_name == "MAIN-PARA"
    assert "DISPLAY" in item.original
    assert "print" in item.suggested_translation
    assert "--- original.cbl" in item.unified_diff
    assert item.confidence_score > 0
    assert item.risk_flags == []

    regenerated = service.reject_and_regenerate(session.id)
    assert regenerated.status == "pending"
    assert regenerated.regeneration_count == 1
    assert "Regenerated translation" in regenerated.suggested_translation

    accepted = service.accept(session.id, edited_translation="return 'done'")
    assert accepted.status == "accepted"
    assert accepted.suggested_translation == "return 'done'"
    assert service.current_item(session.id) is None


def test_fastapi_routes_use_injected_session_service() -> None:
    service = RewriteSessionService()
    client = TestClient(create_app(service))

    created = client.post("/sessions", json={"source": SOURCE, "session_id": "api-demo"})

    assert created.status_code == 200
    assert created.json()["id"] == "api-demo"

    rejected = client.post("/sessions/api-demo/reject")
    assert rejected.status_code == 200
    assert rejected.json()["regeneration_count"] == 1

    accepted = client.post("/sessions/api-demo/accept", json={"suggested_translation": "return"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"


def test_tui_build_session_loads_json_source(tmp_path: Path) -> None:
    service = RewriteSessionService()
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps({"id": "json-demo", "source": SOURCE}), encoding="utf-8")

    session = build_session(Namespace(session_id=None, session=session_file, source=None), service)

    assert session.id == "json-demo"
    assert session.items[0].paragraph_name == "MAIN-PARA"
