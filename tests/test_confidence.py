import pytest

from punchcard.backend.llm.confidence import score_paragraph
from punchcard.backend.parser.ir import DataDiv, Paragraph, Statement


def _statement(text: str, *, line_number: int = 1) -> Statement:
    tokens = tuple(text.upper().replace(".", "").split())
    return Statement(verb=tokens[0], text=text, line_number=line_number, tokens=tokens)


def test_known_go_to_paragraph_scores_below_mandatory_review_threshold() -> None:
    paragraph = Paragraph(
        name="LEGACY-JUMP",
        line_number=10,
        statements=(
            _statement("GO TO ERROR-PARA", line_number=11),
            _statement("ALTER NEXT-PARA TO PROCEED TO DONE-PARA", line_number=12),
        ),
    )

    result = score_paragraph(paragraph)

    assert result.score == pytest.approx(0.1)
    assert result.score < 0.6
    assert "GO_TO" in result.risk_flags
    assert "ALTER" in result.risk_flags
    assert "MANDATORY_REVIEW" in result.risk_flags


def test_data_division_redefines_adds_risk_penalty() -> None:
    paragraph = Paragraph(
        name="SAFE-PARA",
        line_number=20,
        statements=(_statement("DISPLAY CUSTOMER-REC", line_number=21),),
    )
    data_div = DataDiv(lines=("01 CUSTOMER-ALT REDEFINES CUSTOMER-REC PIC X(10).",))

    result = score_paragraph(paragraph, data_div)

    assert result.score == pytest.approx(0.85)
    assert "REDEFINES" in result.risk_flags


def test_file_io_and_external_calls_are_flagged_and_clamped() -> None:
    paragraph = Paragraph(
        name="RISKY-IO",
        line_number=30,
        statements=(
            _statement("CALL 'PAYROLL-ENGINE'", line_number=31),
            _statement("OPEN INPUT PAYROLL-FILE", line_number=32),
            _statement("READ PAYROLL-FILE", line_number=33),
            _statement("WRITE PAYROLL-OUT", line_number=34),
            _statement("CLOSE PAYROLL-FILE", line_number=35),
            _statement("ALTER NEXT-PARA TO PROCEED TO DONE-PARA", line_number=36),
            _statement("GO TO DONE-PARA", line_number=37),
        ),
    )

    result = score_paragraph(paragraph)

    assert result.score == 0.0
    assert "EXTERNAL_CALL" in result.risk_flags
    assert "FILE_IO_OPEN" in result.risk_flags
    assert "FILE_IO_READ" in result.risk_flags
    assert "FILE_IO_WRITE" in result.risk_flags
    assert "FILE_IO_CLOSE" in result.risk_flags
    assert "MANDATORY_REVIEW" in result.risk_flags
