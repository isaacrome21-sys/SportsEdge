from datetime import datetime, timezone

from sportsedge.manual_quote_live import partition_live_rows

AS_OF = datetime(2026, 9, 30, 4, 27, tzinfo=timezone.utc)


def _row(**overrides):
    base = {
        "game_id": "Philadelphia Phillies@Atlanta Braves",
        "market_type": "MONEYLINE",
        "side": "AWAY",
        "line": 0,
        "price": -117,
        "paired_side": "HOME",
        "paired_price": -103,
        "book": "draftkings",
        "observed_at": "2026-09-29T16:00:00+00:00",
        "first_pitch_at": "2026-09-30T17:00:00+00:00",
        "source": "MANUAL",
    }
    base.update(overrides)
    return base


def test_complete_lines_price_after_first_pitch() -> None:
    rows = [_row(
        observed_at="2026-09-30T04:27:25+00:00",
        first_pitch_at="2026-09-29T16:00:00+00:00",
    )]
    live, blocked, notes = partition_live_rows(rows, run_date="2026-09-29", max_age_minutes=60, as_of=AS_OF)
    assert blocked == []
    assert live
    assert notes[0]["reason"] == "MANUAL_QUOTE_NOT_PREGAME"


def test_started_game_with_valid_observed_still_prices() -> None:
    rows = [_row(
        observed_at="2026-09-29T16:00:00+00:00",
        first_pitch_at="2026-09-30T03:00:00+00:00",
    )]
    live, blocked, notes = partition_live_rows(rows, run_date="2026-09-29", max_age_minutes=60, as_of=AS_OF)
    assert blocked == []
    assert len(live) == 1
    assert notes and "FIRST_PITCH_PASSED" in notes[0]["reason"]


def test_ambiguous_bind_still_blocks() -> None:
    rows = [_row(bind_status="AMBIGUOUS_GAME")]
    live, blocked, _notes = partition_live_rows(rows, run_date="2026-09-29", max_age_minutes=60, as_of=AS_OF)
    assert live == []
    assert blocked[0]["reason"] == "AMBIGUOUS_GAME"
