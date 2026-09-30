import pytest

from sportsedge.mlb_issue_body import IssueLinesError, extract_issue_lines
from sportsedge.mlb_lines_intake import LinesIntakeError, parse_lines


def test_ignores_notes_after_fence() -> None:
    body = "### Lines\n```\nPhillies @ Braves\nML -117 -103\n```\nSmoke test: pair ML and RL both sides.\n"
    text = extract_issue_lines(body)
    assert "Phillies @ Braves" in text
    assert "Smoke test" not in text


def test_ignores_notes_before_fence() -> None:
    body = "### Lines\nignore this\n```\nPhillies @ Braves\nML -117 -103\n```\n"
    text = extract_issue_lines(body)
    assert "ignore this" not in text
    assert "Phillies @ Braves" in text


def test_text_fence_tag() -> None:
    body = "### Lines\n```text\nPhillies @ Braves\nML -117 -103\n```\n"
    assert "Phillies @ Braves" in extract_issue_lines(body)


def test_no_fence_keeps_old_behavior() -> None:
    body = "### Lines\nPhillies @ Braves\nML -117 -103\n"
    assert extract_issue_lines(body).startswith("Phillies @ Braves")


def test_bad_line_inside_fence_still_fails() -> None:
    body = "### Lines\n```\nPhillies @ Braves\nML -117\n```\n"
    text = extract_issue_lines(body)
    with pytest.raises(LinesIntakeError):
        parse_lines(text)


def test_unclosed_fence_fails_closed() -> None:
    body = "### Lines\n```\nPhillies @ Braves\nML -117 -103\nnote after\n"
    with pytest.raises(IssueLinesError, match="UNCLOSED_FENCE"):
        extract_issue_lines(body)
