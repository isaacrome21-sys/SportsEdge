"""NHL intake Captured line + pregame pick ledger rows (fail closed)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from datetime import datetime

import pytest

from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines, tickets_to_dict

spec = importlib.util.spec_from_file_location(
    "render_nhl_ledger", Path(__file__).resolve().parents[1] / "scripts" / "render_nhl_myspari_card.py")
card = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card)

BOARD = "[NHL LINES]\nCaptured: 2026-10-24T18:00:00-05:00\nRangers @ Bruins\nML +124 -148\nPL +1.5 -500 +400\nTotal 5.5 +300 +300\n"


def _ticket(body: str) -> dict:
    t = tickets_to_dict(parse_nhl_lines(body), observed_at="2026-10-24T19:00:00-05:00")
    t.update(slate="2026-10-24", issue="9")
    return t


def test_board_captured_line_applies_to_games():
    g = parse_nhl_lines(BOARD)[0]
    assert g.captured_at == "2026-10-24T18:00:00-05:00"


def test_per_game_captured_overrides_board():
    g = parse_nhl_lines("Rangers @ Bruins\nCaptured 2026-10-24T17:00:00Z\nTotal 5.5 -110 -110")[0]
    assert g.captured_at == "2026-10-24T17:00:00+00:00"


@pytest.mark.parametrize("bad", ["Captured: 2026-10-24T18:00:00", "Captured: 2026-10-24", "Captured: soon"])
def test_captured_requires_offset_instant(bad):
    with pytest.raises(NhlLinesIntakeError):
        parse_nhl_lines(f"{bad}\nRangers @ Bruins\nTotal 5.5 -110 -110")


def test_rows_have_price_capture_and_stay_lean():
    rows = card.ledger_rows(_ticket(BOARD), as_of=datetime.fromisoformat('2026-10-24T18:30:00-05:00'))
    assert rows, "+300 both sides of a 5.5 total must clear the floor"
    assert [r["ev"] for r in rows] == sorted((r["ev"] for r in rows), reverse=True)
    for r in rows:
        assert r["market"] in {"TOTAL", "PUCK_LINE"}
        assert r["captured_at"] == "2026-10-24T18:00:00-05:00"
        assert r["tag"] == "LEAN" and r["ev"] >= card.FLOOR
        assert r["result"] is None and r["clv"] is None
    assert not any(r["market"] == "MONEYLINE" for r in rows)


def test_no_captured_line_logs_nothing():
    assert card.ledger_rows(_ticket("Rangers @ Bruins\nTotal 5.5 +300 +300")) == []


def test_unknown_team_logs_nothing():
    assert card.ledger_rows(_ticket("Captured: 2026-10-24T18:00:00-05:00\nFoo @ Bar\nTotal 5.5 +300 +300")) == []


def test_nhl_capture_30_minute_boundary_is_inclusive():
    ticket = _ticket(BOARD)
    exact = datetime.fromisoformat("2026-10-24T18:30:00-05:00")
    late = datetime.fromisoformat("2026-10-24T18:30:01-05:00")
    assert card.QUOTE_MAX_AGE_SECONDS == 1800
    assert card.quote_refusal(ticket["games"][0]["captured_at"], as_of=exact) is None
    assert card.ledger_rows(ticket, as_of=exact)
    assert card.quote_refusal(ticket["games"][0]["captured_at"], as_of=late) == "QUOTE_STALE_OVER_1800S"
    assert card.ledger_rows(ticket, as_of=late) == []
    lines = "\n".join(card.render_lines(ticket, as_of=late))
    assert "QUOTE_STALE_OVER_1800S" in lines
    assert " LEAN" not in lines and " BET" not in lines


@pytest.mark.parametrize(
    ("capture", "instant", "reason"),
    [
        ("2026-10-24T18:00:01-05:00", "2026-10-24T18:00:00-05:00", "QUOTE_TIMESTAMP_IN_FUTURE"),
        (None, "2026-10-24T18:00:00-05:00", "QUOTE_FRESHNESS_UNVERIFIED"),
        ("2026-10-24T18:00:00", "2026-10-24T18:00:00-05:00", "QUOTE_TIMESTAMP_INVALID"),
        ("garbage", "2026-10-24T18:00:00-05:00", "QUOTE_TIMESTAMP_INVALID"),
    ],
)
def test_missing_future_and_invalid_capture_never_prices_or_logs(capture, instant, reason):
    ticket = _ticket(BOARD)
    ticket["games"][0]["captured_at"] = capture
    as_of = datetime.fromisoformat(instant)
    assert card.quote_refusal(capture, as_of=as_of) == reason
    assert card.ledger_rows(ticket, as_of=as_of) == []
    lines = "\n".join(card.render_lines(ticket, as_of=as_of))
    assert reason in lines
    assert " LEAN" not in lines and " BET" not in lines


def test_timestamp_from_issue_edit_never_refreshes_stale_dk_quote():
    ticket = _ticket(BOARD)
    ticket["observed_at"] = "2026-10-24T18:29:59-05:00"
    ticket["games"][0]["captured_at"] = "2026-10-24T17:50:00-05:00"
    as_of = datetime.fromisoformat("2026-10-24T18:30:00-05:00")
    assert card.ledger_rows(ticket, as_of=as_of) == []
    assert "QUOTE_STALE_OVER_1800S" in "\n".join(card.render_lines(ticket, as_of=as_of))
