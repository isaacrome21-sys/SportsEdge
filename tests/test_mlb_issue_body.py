from sportsedge.mlb_issue_body import extract_issue_lines


def test_ignores_notes_after_fence() -> None:
    body = """### Lines\n```\nPhillies @ Braves\nML -117 -103\n```\nSmoke test: pair ML and RL both sides. NOT OFFICIAL.\n"""
    text = extract_issue_lines(body)
    assert "Phillies @ Braves" in text
    assert "Smoke test" not in text
    assert "NOT OFFICIAL" not in text
