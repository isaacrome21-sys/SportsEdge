from datetime import datetime, timezone

import pytest

from sportsedge.mlb_lines_intake import LinesIntakeError
from sportsedge.mlb_resolve import resolve_game
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
        retrieved_at="2026-09-30T10:00:00+00:00",
    )


def test_same_day_two_pregame_starts_are_ambiguous() -> None:
    schedule = [
        _snap(1, "2026-09-30T17:20:00+00:00"),
        _snap(2, "2026-09-30T23:20:00+00:00"),
    ]
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(LinesIntakeError, match="AMBIGUOUS_GAME"):
        resolve_game("Phillies", "Braves", schedule, now=now)


def test_two_day_series_binds_earliest_unplayed() -> None:
    schedule = [
        _snap(1, "2026-09-29T23:20:00+00:00"),
        _snap(2, "2026-09-30T17:20:00+00:00"),
    ]
    now = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)
    game = resolve_game("Phillies", "Braves", schedule, now=now)
    assert game.game_pk == 1
