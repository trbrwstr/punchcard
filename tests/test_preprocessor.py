from pathlib import Path

import pytest

from punchcard.backend.parser import parse_cobol
from punchcard.backend.parser.preprocessor import CopybookNotFoundError, preprocess

PROGRAM_TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
{copy_line}
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_source_without_directives_is_returned_unchanged() -> None:
    source = Path("fixtures/payroll.cbl").read_text(encoding="utf-8")
    assert preprocess(source) == source


def test_copy_is_expanded_from_search_path(tmp_path: Path) -> None:
    _write(tmp_path / "REC.cpy", "       01 WS-FLAG PIC X VALUE 'Y'.\n")
    source = PROGRAM_TEMPLATE.format(copy_line="       COPY REC.")

    expanded = preprocess(source, copybook_paths=[tmp_path])

    assert "WS-FLAG PIC X VALUE 'Y'" in expanded
    assert "COPY" not in expanded


def test_copy_replacing_substitutes_pseudo_text(tmp_path: Path) -> None:
    _write(tmp_path / "REC.cpy", "       01 WS-GREETING PIC X(12).\n")
    source = PROGRAM_TEMPLATE.format(copy_line="       COPY REC REPLACING ==WS-GREETING== BY ==WS-HELLO==.")

    expanded = preprocess(source, copybook_paths=[tmp_path])

    assert "WS-HELLO PIC X(12)" in expanded
    assert "WS-GREETING" not in expanded


def test_nested_copy_is_expanded(tmp_path: Path) -> None:
    _write(tmp_path / "INNER.cpy", "       01 WS-INNER PIC 9.\n")
    _write(tmp_path / "OUTER.cpy", "       01 WS-OUTER PIC 9.\n       COPY INNER.\n")
    source = PROGRAM_TEMPLATE.format(copy_line="       COPY OUTER.")

    expanded = preprocess(source, copybook_paths=[tmp_path])

    assert "WS-OUTER" in expanded
    assert "WS-INNER" in expanded
    assert "COPY" not in expanded


def test_copy_cycle_is_detected_without_recursing_forever(tmp_path: Path) -> None:
    _write(tmp_path / "A.cpy", "       01 WS-A PIC 9.\n       COPY B.\n")
    _write(tmp_path / "B.cpy", "       01 WS-B PIC 9.\n       COPY A.\n")
    source = PROGRAM_TEMPLATE.format(copy_line="       COPY A.")

    expanded = preprocess(source, copybook_paths=[tmp_path])

    assert "WS-A" in expanded
    assert "WS-B" in expanded
    assert "COPY CYCLE SKIPPED" in expanded


def test_missing_copybook_leaves_marker_then_raises_in_strict(tmp_path: Path) -> None:
    source = PROGRAM_TEMPLATE.format(copy_line="       COPY NOPE.")

    assert "COPYBOOK NOT FOUND: NOPE" in preprocess(source, copybook_paths=[tmp_path])
    with pytest.raises(CopybookNotFoundError):
        preprocess(source, copybook_paths=[tmp_path], strict=True)


def test_replace_statement_applies_between_replace_off() -> None:
    source = (
        "       REPLACE ==FOO== BY ==BAR==.\n"
        "       01 FOO PIC X.\n"
        "       REPLACE OFF.\n"
        "       01 FOO PIC X.\n"
    )

    expanded = preprocess(source)

    lines = [line for line in expanded.splitlines() if "PIC X" in line]
    assert "BAR" in lines[0]  # inside the REPLACE area
    assert "FOO" in lines[1]  # after REPLACE OFF, untouched
    assert "REPLACE" not in expanded


def test_parse_cobol_resolves_copybooks_into_the_ir() -> None:
    source = Path("fixtures/with_copy.cbl").read_text(encoding="utf-8")

    program = parse_cobol(source, copybook_paths=["fixtures/copybooks"])

    assert program.program_id == "WITHCOPY"
    assert {section.name for section in program.data.sections} == {"WORKING-STORAGE"}
    # Fields from the copybook are present in the parsed data division.
    assert any("CUST-ID" in line for line in program.data.lines)
    assert any("CUST-BALANCE" in line for line in program.data.lines)
    # And the procedure that references a copied field parsed normally.
    assert [statement.verb for statement in program.all_statements] == ["MOVE", "DISPLAY", "STOP"]


def test_parse_cobol_without_paths_does_not_break_on_unresolved_copy() -> None:
    source = Path("fixtures/with_copy.cbl").read_text(encoding="utf-8")

    program = parse_cobol(source)

    assert program.program_id == "WITHCOPY"
    assert [statement.verb for statement in program.all_statements] == ["MOVE", "DISPLAY", "STOP"]
