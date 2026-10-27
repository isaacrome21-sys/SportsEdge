import pytest

from sportsedge.sports.nba.clv_ledger import (
    NBALedgerError, capture_rows, clv_summary, closing_quote, grade, pick_row, settle,
)
from sportsedge.sports.nba.lines_card import NBALinesError, parse_lines


def body(ts, spread="-4.5", ml="+150 -180"):
    return f"""[NBA LINES]
Captured: {ts}
Lakers @ Celtics
ML {ml}
Spread {spread} -110 -110
Total 221.5 -110 -110
"""


TIP = "2026-10-24T23:30:00+00:00"


def caps(ts, **kw):
    return capture_rows(parse_lines(body(ts, **kw)), game_date="2026-10-24")


def test_issue_captured_line_parsed_and_required_tz():
    g = parse_lines(body("2026-10-24T17:00:00-05:00"))[0]
    assert g.captured_at == "2026-10-24T17:00:00-05:00"
    with pytest.raises(NBALinesError):
        parse_lines(body("2026-10-24T17:00:00"))


def test_per_game_override_and_no_captured_still_parses():
    g = parse_lines("Lakers @ Celtics\nCaptured: 2026-10-24T22:00:00Z\nML +150 -180\n")[0]
    assert g.captured_at.startswith("2026-10-24T22:00:00")
    assert parse_lines("Lakers @ Celtics\nML +150 -180\n")[0].captured_at is None


def test_capture_rows_two_sided_and_home_spread_flipped():
    rows = caps("2026-10-24T17:00:00-05:00")
    assert len(rows) == 6
    home = [r for r in rows if r["market"] == "SPREAD" and r["side"] == "HOME"][0]
    assert home["line"] == 4.5
    with pytest.raises(NBALedgerError):
        capture_rows(parse_lines("Lakers @ Celtics\nML +150 -180\n"), game_date="2026-10-24")


def test_pick_requires_model_p_and_is_experimental():
    r = caps("2026-10-24T17:00:00-05:00")[0]
    with pytest.raises(NBALedgerError):
        pick_row(r, model_p=None, engine_id="x")
    with pytest.raises(NBALedgerError):
        pick_row(r, model_p=0.5, engine_id="")
    p = pick_row(r, model_p=0.45, engine_id="test")
    assert p["status"] == "EXPERIMENTAL" and p["countable"] is False


def test_close_clv_and_grade():
    entry = caps("2026-10-24T17:00:00-05:00")
    late = caps("2026-10-24T18:20:00-05:00", ml="+130 -155")
    post = caps("2026-10-24T19:00:00-05:00", ml="+300 -400")
    p = pick_row(entry[0], model_p=0.45, engine_id="test")  # AWAY ML +150
    s = settle(p, entry + late + post, tip_utc=TIP, away_pts=110, home_pts=104)
    assert s["close_reason"] == "OK" and s["close_american"] == 130
    assert s["clv_prob"] > 0 and s["result"] == "WIN" and s["profit_units"] == pytest.approx(1.5)
    summ = clv_summary([s])
    assert summ["MONEYLINE"]["beat_close_rate"] == 1.0
    assert summ["MONEYLINE"]["status"] == "EXPERIMENTAL_NO_VERDICT"


def test_line_moved_and_post_tip_reasons():
    entry = caps("2026-10-24T17:00:00-05:00")
    moved = caps("2026-10-24T18:20:00-05:00", spread="-5.5")
    sp = pick_row([r for r in entry if r["market"] == "SPREAD"][0], model_p=0.5, engine_id="t")
    assert closing_quote(sp, entry + moved, tip_utc=TIP)[1] == "LINE_MOVED"
    post_only = caps("2026-10-24T19:00:00-05:00")
    assert closing_quote(sp, post_only, tip_utc=TIP)[1] == "CLOSE_NOT_PRETIP"


def test_grade_spread_total_push():
    base = {"line": -4.5, "market": "SPREAD", "side": "AWAY"}
    assert grade(base, away_pts=110, home_pts=105) == "WIN"
    assert grade({**base, "line": 5.0, "side": "HOME"}, away_pts=110, home_pts=105) == "PUSH"
    assert grade({"market": "TOTAL", "side": "UNDER", "line": 221.5}, away_pts=110, home_pts=105) == "WIN"
