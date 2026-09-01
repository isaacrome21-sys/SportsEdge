from datetime import datetime, timezone
import json

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.context_source_adapters import assert_official_injury_uri
from sportsedge.sports.nfl.history import NFLVERSE_SCHEDULE_CSV
from sportsedge.sports.nfl.run_it_context import (
    build_run_it_context,
    build_run_it_context_from_sources,
)
from sportsedge.sports.nfl.stadium_registry import load_stadium_registry


class _Response:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _fixture_opener(req, timeout=20):
    url = req if isinstance(req, str) else req.full_url
    if url == NFLVERSE_SCHEDULE_CSV:
        text = "\n".join(
            [
                "game_id,season,week,gameday,gametime,away_team,home_team,location,away_rest,home_rest,roof,surface,stadium",
                "2026_00_BUF_NYG,2026,0,2026-09-03,20:00,BUF,NYG,Home,7,7,outdoors,fieldturf,MetLife Stadium",
                "2026_01_PIT_BUF,2026,1,2026-09-10,20:00,PIT,BUF,Home,7,7,outdoors,a_turf,Highmark Stadium",
            ]
        )
        return _Response((text + "\n").encode("utf-8"))
    if url == "https://api.weather.gov/points/42.7731,-78.7922":
        return _Response(
            json.dumps(
                {
                    "properties": {
                        "forecastHourly": "https://api.weather.gov/gridpoints/BUF/1,1/forecast/hourly"
                    }
                }
            ).encode("utf-8")
        )
    if url == "https://api.weather.gov/gridpoints/BUF/1,1/forecast/hourly":
        return _Response(
            json.dumps(
                {
                    "properties": {
                        "periods": [
                            {
                                "startTime": "2026-09-10T20:00:00-04:00",
                                "temperature": 63,
                                "probabilityOfPrecipitation": {"value": 20},
                                "relativeHumidity": {"value": 70},
                                "shortForecast": "Partly Cloudy",
                                "windSpeedMph": 8,
                                "windDirDeg": 270,
                            }
                        ]
                    }
                }
            ).encode("utf-8")
        )
    raise AssertionError(f"unexpected fixture URL: {url}")


def test_stadium_registry_is_hash_bound_and_covers_all_teams():
    registry = load_stadium_registry()
    assert registry["version"] == "2026.1"
    assert len(registry["registry_sha256"]) == 64
    assert len(registry["stadiums"]) == 30
    assert len(registry["team_to_stadium"]) == 32
    assert registry["stadiums"]["att"].roof_type == "RETRACTABLE"
    assert registry["stadiums"]["allegiant"].roof_type == "FIXED"


def test_injury_adapter_rejects_non_official_host():
    with pytest.raises(NFLContextError):
        assert_official_injury_uri("https://example.com/injuries")
    assert assert_official_injury_uri("https://www.nfl.com/injuries/").startswith("https://")


def test_run_it_auto_attempts_all_registered_classes_and_fails_closed():
    as_of = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    bundle = build_run_it_context(
        mode="AUTO",
        game={"game_id": "2026_01_TEST"},
        as_of=as_of,
    )
    assert bundle["collection_mode"] == "AUTO"
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False
    for key in (
        "venue_surface",
        "weather",
        "injury_availability",
        "rest_travel",
        "workload_leash",
        "defensive_matchup",
        "personnel_packages",
        "special_teams",
        "coaching_tendencies",
    ):
        assert bundle["observations"][key]["status"] == "MISSING"


def test_source_driven_auto_needs_no_operator_prefill_for_core_context():
    as_of = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    bundle = build_run_it_context_from_sources(
        mode="AUTO",
        game_id="2026_01_PIT_BUF",
        as_of=as_of,
        opener=_fixture_opener,
    )
    assert bundle["collection_mode"] == "AUTO"
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False

    venue = bundle["observations"]["venue_surface"]
    assert venue["status"] == "AVAILABLE"
    assert venue["payload"]["stadium_id"] == "highmark"
    assert venue["payload"]["surface_type"] == "a_turf"
    assert len(venue["source_sha256"]) == 64

    weather = bundle["observations"]["weather"]
    assert weather["status"] == "AVAILABLE"
    assert weather["payload"]["temp_f"] == 63.0
    assert weather["payload"]["kickoff_source_uri"] == NFLVERSE_SCHEDULE_CSV
    assert len(weather["source_sha256"]) == 64

    rest = bundle["observations"]["rest_travel"]
    assert rest["status"] == "AVAILABLE"
    assert rest["payload"]["BUF"]["days_rest"] == 7
    assert rest["payload"]["BUF"]["consec_road"] == 0
    assert rest["payload"]["PIT"]["days_rest"] == 7
    assert rest["payload"]["PIT"]["consec_road"] == 1
    assert rest["payload"]["BUF"]["travel_distance_km"] is not None

    # Unwired classes remain explicit rather than being inferred from market/social data.
    assert bundle["observations"]["injury_availability"]["status"] == "MISSING"
    assert bundle["observations"]["defensive_matchup"]["status"] == "MISSING"
