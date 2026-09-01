from datetime import datetime, timezone
import json

from sportsedge.sports.nfl.auto_slate import (
    build_nfl_auto_context_slate,
    discover_nfl_auto_games,
)
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


def _schedule_csv():
    return "\n".join(
        [
            "game_id,season,game_type,week,gameday,gametime,away_team,home_team,location,away_rest,home_rest,roof,surface,stadium,away_moneyline,home_moneyline,spread_line,total_line",
            "2026_01_LA_SF,2026,REG,1,2026-09-10,20:00,LA,SF,Home,7,7,outdoors,grass,Levi's Stadium,+125,-145,-2.5,45.5",
            "2026_01_PRE_FAKE,2026,PRE,1,2026-09-10,21:00,BUF,NYG,Home,7,7,outdoors,fieldturf,MetLife Stadium,+100,-120,-1.5,38.5",
            "2026_01_LATE,2026,REG,1,2026-09-12,20:00,PIT,BAL,Home,7,7,outdoors,grass,M&T Bank Stadium,+110,-130,-2.0,42.0",
        ]
    ) + "\n"


def _schedule_opener(req, timeout=20):
    url = req if isinstance(req, str) else req.full_url
    if url == NFLVERSE_SCHEDULE_CSV:
        return _Response(_schedule_csv().encode("utf-8"))
    if url == "https://api.weather.gov/points/37.4030,-121.9700":
        return _Response(
            json.dumps(
                {
                    "properties": {
                        "forecastHourly": "https://api.weather.gov/gridpoints/MTR/1,1/forecast/hourly"
                    }
                }
            ).encode("utf-8")
        )
    if url == "https://api.weather.gov/gridpoints/MTR/1,1/forecast/hourly":
        return _Response(
            json.dumps(
                {
                    "properties": {
                        "periods": [
                            {
                                "startTime": "2026-09-10T20:00:00-04:00",
                                "temperature": 72,
                                "probabilityOfPrecipitation": {"value": 5},
                                "relativeHumidity": {"value": 45},
                                "shortForecast": "Clear",
                                "windSpeedMph": 9,
                                "windDirDeg": 290,
                            }
                        ]
                    }
                }
            ).encode("utf-8")
        )
    raise AssertionError(f"unexpected fixture URL: {url}")


def _depth_rows(team):
    stamp = "2026-09-10T15:00:00+00:00"
    rows = []
    for slot, pos in enumerate(("LT", "LG", "C", "RG", "RT"), start=1):
        rows.append(
            {
                "dt": stamp,
                "team": team,
                "gsis_id": f"{team}-OL-{slot}",
                "pos_abb": pos,
                "pos_slot": slot,
                "pos_rank": 1,
            }
        )
    for slot, pos in enumerate(("CB", "CB", "FS", "SS"), start=20):
        rows.append(
            {
                "dt": stamp,
                "team": team,
                "gsis_id": f"{team}-DB-{slot}",
                "pos_abb": pos,
                "pos_slot": slot,
                "pos_rank": 1,
            }
        )
    return rows


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


def test_auto_slate_end_to_end_adds_pit_personnel_without_promotion():
    depth = _depth_rows("LAR") + _depth_rows("SF")
    slate = build_nfl_auto_context_slate(
        as_of=datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc),
        horizon_minutes=12 * 60,
        depth_chart_rows=depth,
        depth_chart_source_uri="https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2026.csv",
        depth_chart_source_sha256="b" * 64,
        opener=_schedule_opener,
    )
    assert slate["game_count"] == 1
    assert slate["model_p_eligible"] is False
    assert slate["truth_gate_eligible"] is False
    bundle = slate["games"][0]
    assert bundle["observations"]["venue_surface"]["status"] == "AVAILABLE"
    assert bundle["observations"]["weather"]["status"] == "AVAILABLE"
    assert bundle["observations"]["rest_travel"]["status"] == "AVAILABLE"
    personnel = bundle["observations"]["personnel_packages"]
    assert personnel["status"] == "AVAILABLE"
    by_team = {row["team_id"]: row for row in personnel["payload"]["teams"]}
    assert by_team["LAR"]["projected_ol_starters_known"] is True
    assert by_team["SF"]["starting_secondary_known"] is True
    assert personnel["payload"]["missing_team_ids"] == []
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False
