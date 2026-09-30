from datetime import datetime, timezone

from sportsedge.mlb_schedule_filter import filter_schedule_to_first_pitch
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
        retrieved_at="2026-09-30T04:47:41+00:00",
    )


def test_1256_shape_two_day_series_keeps_bound_pitch() -> None:
    day1 = _snap(1, "2026-09-29T17:20:00+00:00")
    day2 = _snap(2, "2026-09-30T17:20:00+00:00")
    kept = filter_schedule_to_first_pitch(
        [day1, day2],
        datetime(2026, 9, 30, 17, 20, tzinfo=timezone.utc),
    )
    assert kept is not None
    assert [g.game_pk for g in kept] == [2]
