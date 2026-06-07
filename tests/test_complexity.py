from punchcard.backend.parser.complexity import (
    complexity_for_source,
    cyclomatic_complexity,
)
from punchcard.backend.parser.ir import Paragraph, Statement


def _statement(text: str, line_number: int = 1) -> Statement:
    tokens = tuple(text.upper().replace(".", "").split())
    return Statement(verb=tokens[0], text=text, line_number=line_number, tokens=tokens)


def test_straight_line_paragraph_has_base_complexity() -> None:
    paragraph = Paragraph(
        name="GREET",
        line_number=1,
        statements=(_statement("DISPLAY 'HELLO'"), _statement("STOP RUN")),
    )

    assert cyclomatic_complexity(paragraph) == 1


def test_branches_and_connectives_each_add_a_path() -> None:
    paragraph = Paragraph(
        name="CHECK",
        line_number=1,
        statements=(
            _statement("IF WS-FLAG = 'Y' AND WS-COUNT > 0"),  # IF + AND -> +2
            _statement("PERFORM CALC-PAY UNTIL WS-DONE"),      # UNTIL -> +1
            _statement("EVALUATE WS-CODE"),                    # no token -> +0
            _statement("WHEN 1"),                              # WHEN -> +1
        ),
    )

    assert cyclomatic_complexity(paragraph) == 1 + 2 + 1 + 1


def test_complexity_for_source_matches_token_scoring() -> None:
    source = "IF A OR B\n    PERFORM P UNTIL DONE\nWHEN OTHER"

    assert complexity_for_source(source) == 1 + 1 + 1 + 1 + 1  # IF, OR, UNTIL, WHEN
