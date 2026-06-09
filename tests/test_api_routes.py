from pathlib import Path

from fastapi.testclient import TestClient

from punchcard.backend.api import routes
from punchcard.backend.main import create_app


def test_rewrite_session_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PUNCHCARD_DATABASE_URL", f"sqlite:///{tmp_path / 'punchcard.sqlite3'}")
    routes._engine = None

    with TestClient(create_app()) as client:
        source = Path("fixtures/hello.cbl").read_text(encoding="utf-8")
        create_response = client.post(
            "/sessions",
            files={"file": ("hello.cbl", source.encode("utf-8"), "text/plain")},
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["id"]

        status_response = client.get(f"/sessions/{session_id}")
        assert status_response.status_code == 200
        assert status_response.json()["program_id"] == "HELLO"
        assert status_response.json()["progress"] == 0.0

        paragraphs_response = client.get(f"/sessions/{session_id}/paragraphs")
        assert paragraphs_response.status_code == 200
        paragraphs = paragraphs_response.json()["paragraphs"]
        assert paragraphs[0]["name"] == "MAIN-PARA"
        assert paragraphs[0]["status"] == "PENDING"

        translate_response = client.post(f"/sessions/{session_id}/paragraphs/MAIN-PARA/translate")
        assert translate_response.status_code == 200
        assert translate_response.json()["status"] == "TRANSLATED"
        assert "MOCK_TRANSLATION" in translate_response.json()["risk_flags"]

        accept_response = client.post(f"/sessions/{session_id}/paragraphs/MAIN-PARA/accept")
        assert accept_response.status_code == 200
        assert accept_response.json()["audit_event_type"] == "ACCEPTED"

        export_response = client.get(f"/sessions/{session_id}/export")
        assert export_response.status_code == 200
        export = export_response.json()
        assert "Proposed Python rewrite" in export["translated_output"]
        assert [event["event_type"] for event in export["audit_log"]] == ["CREATED", "TRANSLATED", "ACCEPTED"]


def test_reject_logs_audit_event_without_translation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PUNCHCARD_DATABASE_URL", f"sqlite:///{tmp_path / 'punchcard.sqlite3'}")
    routes._engine = None

    with TestClient(create_app()) as client:
        source = Path("fixtures/hello.cbl").read_text(encoding="utf-8")
        session_id = client.post(
            "/sessions",
            files={"file": ("hello.cob", source.encode("utf-8"), "text/plain")},
        ).json()["id"]

        response = client.post(f"/sessions/{session_id}/paragraphs/MAIN-PARA/reject")
        assert response.status_code == 200
        assert response.json()["audit_event_type"] == "REJECTED"

        export = client.get(f"/sessions/{session_id}/export").json()
        assert export["audit_log"][-1]["event_type"] == "REJECTED"


def test_confidence_is_structural_and_export_file_is_downloadable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PUNCHCARD_DATABASE_URL", f"sqlite:///{tmp_path / 'punchcard.sqlite3'}")
    routes._engine = None

    with TestClient(create_app()) as client:
        source = Path("fixtures/hello.cbl").read_text(encoding="utf-8")
        session_id = client.post(
            "/sessions",
            files={"file": ("hello.cbl", source.encode("utf-8"), "text/plain")},
        ).json()["id"]

        # Confidence comes from the structural scorer at creation, not the mock.
        paragraph = client.get(f"/sessions/{session_id}/paragraphs").json()["paragraphs"][0]
        assert paragraph["confidence_score"] == 1.0
        assert paragraph["risk_flags"] == []

        translate = client.post(f"/sessions/{session_id}/paragraphs/MAIN-PARA/translate").json()
        assert translate["confidence_score"] == 1.0  # unchanged by translation

        response = client.get(f"/sessions/{session_id}/export/file")
        assert response.status_code == 200
        assert response.headers["content-disposition"] == 'attachment; filename="hello.py"'
        assert "Translated from hello.cbl" in response.text
        assert "# --- MAIN-PARA [TRANSLATED] ---" in response.text
        assert "Proposed Python rewrite" in response.text


def test_target_language_drives_status_and_export_extension(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PUNCHCARD_DATABASE_URL", f"sqlite:///{tmp_path / 'punchcard.sqlite3'}")
    routes._engine = None

    with TestClient(create_app()) as client:
        source = Path("fixtures/hello.cbl").read_text(encoding="utf-8")
        created = client.post(
            "/sessions",
            files={"file": ("hello.cbl", source.encode("utf-8"), "text/plain")},
            data={"target_language": "Java"},
        )
        assert created.status_code == 201
        assert created.json()["target_language"] == "java"  # normalized
        session_id = created.json()["id"]

        assert client.get(f"/sessions/{session_id}").json()["target_language"] == "java"

        client.post(f"/sessions/{session_id}/paragraphs/MAIN-PARA/translate")
        export = client.get(f"/sessions/{session_id}/export/file")
        assert export.headers["content-disposition"] == 'attachment; filename="hello.java"'


def test_paragraph_detail_endpoint_returns_source_and_translation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PUNCHCARD_DATABASE_URL", f"sqlite:///{tmp_path / 'punchcard.sqlite3'}")
    routes._engine = None

    with TestClient(create_app()) as client:
        source = Path("fixtures/hello.cbl").read_text(encoding="utf-8")
        session_id = client.post(
            "/sessions",
            files={"file": ("hello.cbl", source.encode("utf-8"), "text/plain")},
        ).json()["id"]

        before = client.get(f"/sessions/{session_id}/paragraphs/MAIN-PARA")
        assert before.status_code == 200
        assert "DISPLAY" in before.json()["source"]
        assert before.json()["translated_text"] is None

        client.post(f"/sessions/{session_id}/paragraphs/MAIN-PARA/translate")
        after = client.get(f"/sessions/{session_id}/paragraphs/MAIN-PARA").json()
        assert "Proposed Python rewrite" in after["translated_text"]

        missing = client.get(f"/sessions/{session_id}/paragraphs/NOPE")
        assert missing.status_code == 404


def test_target_language_defaults_to_python(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PUNCHCARD_DATABASE_URL", f"sqlite:///{tmp_path / 'punchcard.sqlite3'}")
    routes._engine = None

    with TestClient(create_app()) as client:
        source = Path("fixtures/hello.cbl").read_text(encoding="utf-8")
        created = client.post(
            "/sessions",
            files={"file": ("hello.cbl", source.encode("utf-8"), "text/plain")},
        )
        assert created.json()["target_language"] == "python"


def test_upload_rejects_non_cobol_extension(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PUNCHCARD_DATABASE_URL", f"sqlite:///{tmp_path / 'punchcard.sqlite3'}")
    routes._engine = None

    with TestClient(create_app()) as client:
        response = client.post(
            "/sessions",
            files={"file": ("hello.txt", b"IDENTIFICATION DIVISION.", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload must be a .cbl or .cob file."
