from datetime import datetime, timezone

from sportsedge.manual_quote_live import partition_live_rows


def test_started_game_is_blocked_not_raised() -> None:
    rows = [{
        "game_id": "Padres@Dodgers",
        "market_type": "MONEYLINE",
        "side": "AWAY",
        "line": 0,
        "price": 105,
        "paired_side": "HOME",
        "paired_price": -125,
        "book": "draftkings",
        "observed_at": "2026-09-30T04:27:25+00:00",
        "first_pitch_at": "2026-09-29T16:00:00+00:00",
        "source": "MANUAL",
    }]
    live, blocked = partition_live_rows(
        rows, run_date="2026-09-29", max_age_minutes=60,
        as_of=datetime(2026, 9, 30, 4, 27, tzinfo=timezone.utc),
    )
    assert live == []
    assert "MANUAL_QUOTE" in blocked[0]["reason"]
