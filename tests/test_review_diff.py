from punchcard.backend.review.diff import generate_unified_diff


def test_generate_unified_diff_returns_empty_string_for_unchanged_text() -> None:
    text = "IDENTIFICATION DIVISION.\nPROGRAM-ID. HELLO.\n"

    assert generate_unified_diff(text, text) == ""


def test_generate_unified_diff_marks_changed_text() -> None:
    diff = generate_unified_diff("DISPLAY 'SHALOM'.\n", "print('shalom')\n")

    assert "--- original.cob" in diff
    assert "+++ translated.py" in diff
    assert "-DISPLAY 'SHALOM'." in diff
    assert "+print('shalom')" in diff


def test_generate_unified_diff_marks_inserted_lines() -> None:
    diff = generate_unified_diff("line one\nline three\n", "line one\nline two\nline three\n")

    assert "+line two" in diff
    assert " line one" in diff
    assert " line three" in diff


def test_generate_unified_diff_marks_deleted_lines() -> None:
    diff = generate_unified_diff("line one\nline two\nline three\n", "line one\nline three\n")

    assert "-line two" in diff
    assert " line one" in diff
    assert " line three" in diff


def test_generate_unified_diff_normalizes_line_endings_before_diffing() -> None:
    assert generate_unified_diff("line one\r\nline two\r\n", "line one\nline two\n") == ""
