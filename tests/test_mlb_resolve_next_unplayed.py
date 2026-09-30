from datetime import datetime, timezone

from sportsedge.mlb_resolve import build_bound_input, resolve_game
from sportsedge.mlb_source import GameSnapshot


def _snap(pk: int, when: str, away="Philadelphia Phillies", home="Atlanta Braves") -> GameSnapshot:
    return GameSnapshot(
        game_pk=pk,
        game_date=when,
        status="Scheduled",
        away_id=143,
        away_name=away,
        home_id=144,
        home_name=home,
        away_probable_pitcher_id=None,
        away_probable_pitcher_name=None,
        home_probable_pitcher_id=None,
        home_probable_pitcher_name=None,
        retrieved_at="2026-09-29T23:00:00+00:00",
    )


def test_same_matchup_picks_unplayed_day_two() -> None:
    day1 = _snap(1, "2026-09-29T17:00:00+00:00")
    day2 = _snap(2, "2026-09-30T17:00:00+00:00")
    now = datetime(2026, 9, 30, 4, 27, tzinfo=timezone.utc)
    game = resolve_game("Phillies", "Braves", [day1, day2], now=now)
    assert game.game_pk == 2


def test_started_and_pregame_no_exception() -> None:
    started = _snap(1, "2026-09-29T17:00:00+00:00", "Chicago White Sox", "Houston Astros")
    live = _snap(2, "2026-09-30T17:00:00+00:00")
    now = datetime(2026, 9, 30, 4, 27, tzinfo=timezone.utc)
    text = "White Sox @ Astros\nML +128 -155\n\nPhillies @ Braves\nML -117 -103\n"
    payload = build_bound_input(text, observed_at=now.isoformat(), schedule=[started, live])
    statuses = {row.get("bind_status"): row for row in payload["rows"]}
    assert "GAME_NOT_PREGAME" in statuses
    assert statuses["GAME_NOT_PREGAME"]["first_pitch_at"] is None
    priced = [row for row in payload["rows"] if not row.get("bind_status")]
    assert len(priced) == 1
    assert priced[0]["first_pitch_at"].startswith("2026-09-30")


def test_canonical_resolve_uses_first_pitch_when_two_days() -> None:
    from sportsedge.canonical_manual_mlb import _resolve_game
    from sportsedge.manual_quote import validate_manual_quote

    day1 = _snap(1, "2026-09-29T17:00:00+00:00")
    day2 = _snap(2, "2026-09-30T17:00:00+00:00")
    row = validate_manual_quote({
        "game_id": "Philadelphia Phillies@Atlanta Braves",
        "market_type": "MONEYLINE",
        "side": "AWAY",
        "line": 0,
        "price": -117,
        "paired_side": "HOME",
        "paired_price": -103,
        "book": "draftkings",
        "observed_at": "2026-09-30T04:47:41+00:00",
        "first_pitch_at": "2026-09-30T17:00:00+00:00",
        "source": "MANUAL",
    })
    game = _resolve_game(row, schedule=[day1, day2])
    assert game.game_pk == 2
