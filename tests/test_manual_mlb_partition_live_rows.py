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


def test_game_started_with_valid_pregame_observed() -> None:
    rows = [_row(
        observed_at="2026-09-29T16:00:00+00:00",
        first_pitch_at="2026-09-30T03:00:00+00:00",
    )]
    live, blocked = partition_live_rows(rows, run_date="2026-09-29", max_age_minutes=60, as_of=AS_OF)
    assert live == []
    assert blocked[0]["reason"].startswith("MANUAL_QUOTE_GAME_STARTED")


def test_date_mismatch() -> None:
    rows = [_row(first_pitch_at="2026-10-02T17:00:00+00:00")]
    live, blocked = partition_live_rows(rows, run_date="2026-09-29", max_age_minutes=60, as_of=AS_OF)
    assert live == []
    assert "DATE_MISMATCH" in blocked[0]["reason"]


def test_mixed_live_and_blocked() -> None:
    good = _row()
    bad = _row(
        game_id="Chicago White Sox@Houston Astros",
        first_pitch_at="2026-09-30T03:00:00+00:00",
    )
    live, blocked = partition_live_rows([bad, good], run_date="2026-09-29", max_age_minutes=60, as_of=AS_OF)
    assert [r["game_id"] for r in live] == [good["game_id"]]
    assert blocked[0]["reason"].startswith("MANUAL_QUOTE_GAME_STARTED")
