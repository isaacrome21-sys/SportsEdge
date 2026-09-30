from datetime import datetime, timezone

from sportsedge.mlb_resolve import build_bound_input, resolve_game
from sportsedge.mlb_source import GameSnapshot


def _snap(pk: int, when: str) -> GameSnapshot:
    return GameSnapshot(
        game_pk=pk,
        game_date=when,
        status="Scheduled",
        away_id=143,
        away_name="Philadelphia Phillies",
        home_id=144,
        home_name="Atlanta Braves",
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
    payload = build_bound_input(
        "Phillies @ Braves\nML -117 -103\n",
        observed_at=now.isoformat(),
        schedule=[day1, day2],
    )
    assert payload["rows"][0]["first_pitch_at"].startswith("2026-09-30")
