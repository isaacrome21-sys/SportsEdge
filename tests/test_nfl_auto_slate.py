from datetime import datetime, timezone

from sportsedge.sports.nfl.auto_slate import discover_nfl_auto_games
from sportsedge.sports.nfl.history import NFLVERSE_SCHEDULE_CSV


class _Response:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _schedule_opener(req, timeout=20):
    url = req if isinstance(req, str) else req.full_url
    assert url == NFLVERSE_SCHEDULE_CSV
    text = "\n".join(
        [
            "game_id,season,game_type,week,gameday,gametime,away_team,home_team,location,away_rest,home_rest,roof,surface,stadium,away_moneyline,home_moneyline,spread_line,total_line",
            "2026_01_LA_SF,2026,REG,1,2026-09-10,20:00,LA,SF,Home,7,7,outdoors,grass,Levi's Stadium,+125,-145,-2.5,45.5",
            "2026_01_PRE_FAKE,2026,PRE,1,2026-09-10,21:00,BUF,NYG,Home,7,7,outdoors,fieldturf,MetLife Stadium,+100,-120,-1.5,38.5",
            "2026_01_LATE,2026,REG,1,2026-09-12,20:00,PIT,BAL,Home,7,7,outdoors,grass,M&T Bank Stadium,+110,-130,-2.0,42.0",
        ]
    )
    return _Response((text + "\n").encode("utf-8"))


def _keys(value):
    if isinstance(value, dict):
        out = set(value)
        for child in value.values():
            out |= _keys(child)
        return out
    if isinstance(value, (list, tuple)):
        out = set()
        for child in value:
            out |= _keys(child)
        return out
    return set()


def test_auto_slate_discovers_reg_games_without_operator_game_ids():
    plan = discover_nfl_auto_games(
        as_of=datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc),
        min_lead_minutes=0,
        horizon_minutes=12 * 60,
        opener=_schedule_opener,
    )
    assert len(plan["games"]) == 1
    assert plan["games"][0]["game_id"] == "2026_01_LA_SF"
    assert plan["games"][0]["away_team_id"] == "LAR"
    assert plan["games"][0]["home_team_id"] == "SF"
    assert len(plan["schedule_source_sha256"]) == 64


def test_auto_slate_never_copies_schedule_betting_columns():
    plan = discover_nfl_auto_games(
        as_of=datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc),
        horizon_minutes=12 * 60,
        opener=_schedule_opener,
    )
    keys = _keys(plan)
    assert {
        "away_moneyline",
        "home_moneyline",
        "spread_line",
        "total_line",
        "away_spread_odds",
        "home_spread_odds",
        "over_odds",
        "under_odds",
    }.isdisjoint(keys)
