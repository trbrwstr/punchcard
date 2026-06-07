from pathlib import Path

from punchcard.backend.parser import parse_cobol

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
