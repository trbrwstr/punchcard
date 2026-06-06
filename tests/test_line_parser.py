from pathlib import Path

from punchcard.backend.parser import parse_cobol


def test_parse_fixture_program() -> None:
    source = Path("fixtures/hello.cbl").read_text(encoding="utf-8")

    program = parse_cobol(source)

    assert program.program_id == "HELLO"
    assert program.data.sections[0].name == "WORKING-STORAGE"
    assert program.procedure.paragraphs[0].name == "MAIN-PARA"
    assert [statement.verb for statement in program.all_statements] == ["DISPLAY", "MOVE", "STOP"]
