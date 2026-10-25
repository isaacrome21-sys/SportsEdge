import json
import sys
from datetime import datetime, timezone

import pytest

from scripts import run_nba_lines_issue as runner
from sportsedge.sports.nba.lines_card import parse_lines

BODY = """Memphis Grizzlies @ Sacramento Kings
Captured: 2026-10-25T12:52:42-05:00
Spread -3.5 -105 -115
Total 234.5 -110 -110
ML -166 +140
"""


def test_blocked_cli_preserves_quotes_without_history_or_hidden_pricing(tmp_path, monkeypatch):
    body = tmp_path / "body.txt"
    body.write_text(BODY)
    out = tmp_path / "card.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_nba_lines_issue.py", "--body-file", str(body),
        "--observed-at", "2026-10-25T21:46:00Z", "--issue", "2623",
        "--game-date", "2026-10-25", "--engine-id", "test-v1", "--out", str(out)])
    def forbidden(*args, **kwargs):
        pytest.fail("Blocked board must not fetch history or calculate model prices")
    for name in ("fetch_results", "ratings_from_results", "render", "price_game"):
        monkeypatch.setattr(runner, name, forbidden)
    assert runner.main() == 0
    card = out.read_text()
    assert "FAMILY_REGISTRY_NOT_VALIDATED" in card
    assert "-105 / -115" in card and "-166 / +140" in card
    assert "2026-10-25T12:52:42-05:00" in card
    assert "Editing an issue does not refresh its capture" in card
    assert json.loads((tmp_path / "picks.json").read_text()) == []
    captures = [json.loads(x) for x in (tmp_path / "captures.jsonl").read_text().splitlines()]
    assert len(captures) == 6
    assert {c["captured_at"] for c in captures} == {"2026-10-25T12:52:42-05:00"}
    assert not any("model_p" in c for c in captures)


def test_capture_age_uses_book_capture_not_issue_time():
    card = runner.blocked_quote_card(parse_lines(BODY),
        as_of=datetime(2026, 10, 25, 18, 52, 42, tzinfo=timezone.utc))
    assert "Capture age at audit: 3600 seconds" in card
    assert "not model prices or recommendations" in card
    assert "Game start and current availability are not verified" in card


def test_future_capture_is_unverified_not_current():
    card = runner.blocked_quote_card(parse_lines(BODY),
        as_of=datetime(2026, 10, 25, 17, 52, 41, tzinfo=timezone.utc))
    assert "in the future; quote unverified" in card


def test_naive_audit_clock_refused():
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        runner.blocked_quote_card(parse_lines(BODY), as_of=datetime(2026, 10, 25))
