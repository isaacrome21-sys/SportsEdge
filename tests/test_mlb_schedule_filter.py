from sportsedge.mlb_schedule_filter import filter_schedule_to_game_pk
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


def test_filters_two_day_series_by_game_pk() -> None:
    day1 = _snap(111, "2026-09-29T17:20:00+00:00")
    day2 = _snap(222, "2026-09-30T17:20:00+00:00")
    kept = filter_schedule_to_game_pk([day1, day2], 222)
    assert [g.game_pk for g in kept] == [222]


def test_missing_game_pk_returns_empty() -> None:
    day1 = _snap(111, "2026-09-29T17:20:00+00:00")
    assert filter_schedule_to_game_pk([day1], None) == []
