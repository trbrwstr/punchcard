from pathlib import Path
from types import SimpleNamespace

import asyncio
from fastapi.testclient import TestClient

from punchcard.backend.api import create_app
from punchcard.backend.llm import AnthropicTranslator, render_translation_prompt
from punchcard.backend.parser import parse_cobol
from punchcard.backend.review import ReviewSession, export_session, score_program_confidence

FIXTURE_PATHS = [
    Path("fixtures/payroll.cbl"),
    Path("fixtures/inventory_lookup.cbl"),
    Path("fixtures/report_generation.cbl"),
]

REQUIRED_VERBS = {
    "MOVE",
    "ADD",
    "SUBTRACT",
    "MULTIPLY",
    "DIVIDE",
    "COMPUTE",
    "IF",
    "ELSE",
    "END-IF",
    "PERFORM",
    "EVALUATE",
    "WHEN",
    "CALL",
    "READ",
    "WRITE",
    "OPEN",
    "CLOSE",
    "STOP",
    "GOBACK",
    "GO",
}


def _program_for(path: Path):
    return parse_cobol(path.read_text(encoding="utf-8"))


def test_fixture_programs_cover_required_cobol_verbs() -> None:
    verbs: set[str] = set()

    for path in FIXTURE_PATHS:
        program = _program_for(path)
        assert program.program_id
        assert program.data.sections
        assert program.all_statements
        verbs.update(statement.verb for statement in program.all_statements)

    assert REQUIRED_VERBS <= verbs


def test_parser_ir_construction_keeps_sections_paragraphs_and_line_numbers() -> None:
    program = _program_for(Path("fixtures/payroll.cbl"))

    assert program.program_id == "PAYROLL"
    assert program.environment.sections[0].name == "INPUT-OUTPUT"
    assert {section.name for section in program.data.sections} == {"FILE", "WORKING-STORAGE"}
    assert [paragraph.name for paragraph in program.procedure.paragraphs] == [
        "MAIN-PARA",
        "CALCULATE-PAY",
        "WRITE-REPORT",
    ]
    assert any(statement.verb == "CALL" and "AUDITPAY" in statement.text for statement in program.all_statements)
    assert all(statement.line_number > 0 for statement in program.all_statements)


def test_confidence_scoring_is_explainable_and_penalizes_unsupported_verbs() -> None:
    strong_program = _program_for(Path("fixtures/report_generation.cbl"))
    weak_program = parse_cobol(
        """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OYVEY.
       PROCEDURE DIVISION.
       MAIN.
           FARBRENGEN WITH UNKNOWN-THING.
           IF WS-FLAG = "Y".
        """
    )

    strong_score = score_program_confidence(strong_program)
    weak_score = score_program_confidence(weak_program)

    assert strong_score.score > 0.90
    assert strong_score.supported_statement_ratio == 1.0
    assert strong_score.total_statements == len(strong_program.all_statements)
    assert strong_score.reasons
    assert weak_score.score < strong_score.score
    assert any("not balanced" in reason for reason in weak_score.reasons)


def test_prompt_rendering_includes_guardrails_source_lines_and_confidence() -> None:
    program = _program_for(Path("fixtures/inventory_lookup.cbl"))
    confidence = score_program_confidence(program)

    prompt = render_translation_prompt(program, confidence)

    assert "Program: INVLOOK" in prompt
    assert "Confidence:" in prompt
    assert "Do not invent files" in prompt
    assert "PROCEDURE statements" in prompt
    assert "GO TO READ-NEXT" in prompt
    assert "Return JSON" in prompt


def test_mocked_anthropic_translation_uses_injected_client_without_network() -> None:
    calls: list[dict[str, object]] = []

    class FakeMessages:
        def create(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(text='{"summary":"mocked"}')])

    fake_client = SimpleNamespace(messages=FakeMessages())
    translator = AnthropicTranslator(client=fake_client, model="test-model")

    result = asyncio.run(translator.translate("Translate this, nu."))

    assert result == '{"summary":"mocked"}'
    assert calls[0]["model"] == "test-model"
    assert calls[0]["messages"] == [{"role": "user", "content": "Translate this, nu."}]


def test_fastapi_session_endpoints_use_injected_translator() -> None:
    class FakeTranslator:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def translate(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return '{"summary":"api mocked"}'

    translator = FakeTranslator()
    app = create_app(translator=translator)
    client = TestClient(app)
    source = Path("fixtures/payroll.cbl").read_text(encoding="utf-8")

    create_response = client.post("/sessions", json={"source": source})
    assert create_response.status_code == 201
    session = create_response.json()
    assert session["program_id"] == "PAYROLL"
    assert session["statements"] > 0

    get_response = client.get(f"/sessions/{session['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == session["id"]

    translate_response = client.post(f"/sessions/{session['id']}/translate")
    assert translate_response.status_code == 200
    assert translate_response.json()["translation"] == '{"summary":"api mocked"}'
    assert translator.prompts and "Program: PAYROLL" in translator.prompts[0]


def test_export_output_contains_translation_and_audit_log() -> None:
    program = _program_for(Path("fixtures/payroll.cbl"))
    confidence = score_program_confidence(program)
    session = ReviewSession(source=program.source, program=program, confidence=confidence)
    session.translation = '{"summary":"exported"}'
    session.record("session.created", "Parsed source.")
    session.record("translation.completed", "Stored translation.")

    exported = export_session(session)

    assert exported["program_id"] == "PAYROLL"
    assert exported["confidence"] == confidence.score
    assert exported["translation"] == '{"summary":"exported"}'
    assert exported["audit_log"] == [
        {
            "action": event.action,
            "detail": event.detail,
            "created_at": event.created_at.isoformat(),
        }
        for event in session.audit_log
    ]
