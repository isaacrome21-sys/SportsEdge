"""A Savant/Statcast failure must degrade only the Statcast lane.

Regression for #1457: Padres-Brewers context was NOT RETRIEVED at all because
the per-game 30-day Statcast download timed out (StatcastSourceError), which
also dropped starters, lineups, umpire, weather, park and bullpen lanes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.acquire_mlb_card_context import shared_statcast_snapshot
from sportsedge.mlb_run_it_pregame import acquire_mlb_run_it_pregame
from sportsedge.statcast_daily_source import StatcastSourceError
from tests.test_mlb_run_it_pregame import _Response

AS_OF = datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc)
LIVE = {
    "gameData": {
        "datetime": {"officialDate": "2026-09-22", "dateTime": "2026-09-22T23:10:00Z"},
        "venue": {"id": 3313},
        "teams": {"away": {"id": 10}, "home": {"id": 20}},
        "probablePitchers": {"away": {"id": 501, "fullName": "Away Starter"}, "home": {"id": 502, "fullName": "Home Starter"}},
    },
    "liveData": {"boxscore": {"officials": [], "teams": {"away": {"battingOrder": []}, "home": {"battingOrder": []}}}},
}
PRIOR = {
    "schema_version": "mlb_umpire_prior_test_v1",
    "league_prior": {"runs_per_game": 8.9, "strikeouts_per_game": 16.72, "walks_per_game": 6.32},
    "prior_equivalent_games": 8, "min_home_plate_games": 8, "history_days": 365,
}
VENUE = {"venues": [{"id": 3313, "name": "Example Park",
                     "location": {"city": "Example", "stateAbbrev": "IL", "country": "USA", "latitude": 41.95, "longitude": -87.65},
                     "timeZone": {"id": "America/Chicago"}, "fieldInfo": {"roofType": "Open", "turfType": "Grass", "capacity": 41000}}]}
POINTS = {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/LOT/1,2/forecast/hourly"}}
HOURLY = {"properties": {"periods": [{"startTime": "2026-09-22T23:00:00+00:00", "temperature": 68, "temperatureUnit": "F",
                                      "windSpeed": "7 mph", "windDirection": "SW", "probabilityOfPrecipitation": {"value": 15},
                                      "shortForecast": "Clear", "isDaytime": False}]}}


def _bundle(opener, **kw):
    return acquire_mlb_run_it_pregame(
        game_pk=999005, as_of=AS_OF, opener=opener, live_payload=LIVE, umpire_history_rows=[],
        umpire_prior_config=PRIOR, venue_payload=VENUE, nws_points_payload=POINTS, nws_hourly_payload=HOURLY,
        bullpen_context={"status": "AVAILABLE", "model_p_eligible": False}, **kw,
    )


def _opener(seen):
    def opener(req, timeout=30):
        url = getattr(req, "full_url", str(req))
        seen.append(url)
        if "/roster?" in url:
            return _Response({"roster": []})
        if "/transactions?" in url:
            return _Response({"transactions": []})
        if "baseballsavant" in url:
            raise TimeoutError("The read operation timed out")
        raise AssertionError(f"unexpected network request: {url}")
    return opener


def test_statcast_timeout_keeps_other_lanes():
    seen: list = []
    bundle = _bundle(_opener(seen))
    assert bundle["statcast"]["status"] == "SOURCE_FAILED"
    assert "STATCAST_FETCH_FAILED:TimeoutError" in bundle["statcast"]["error"]
    assert bundle["statcast"]["model_p_eligible"] is False
    assert bundle["model_p_eligible"] is False
    for lane in ("starters", "lineups", "umpire", "park_venue", "weather_roof", "injuries_scratches"):
        assert isinstance(bundle[lane], dict) and bundle[lane].get("status")
    assert bundle["weather_roof"]["forecast"]["temperature"] == 68


def test_known_unavailable_skips_per_game_download():
    seen: list = []
    bundle = _bundle(_opener(seen), statcast_unavailable_reason="STATCAST_FETCH_FAILED:TimeoutError:x")
    assert bundle["statcast"]["status"] == "SOURCE_FAILED"
    assert not any("baseballsavant" in u for u in seen)


def test_shared_snapshot_retries_then_reports_reason():
    calls = {"n": 0}

    def flaky(*, now):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StatcastSourceError("STATCAST_FETCH_FAILED:TimeoutError:t")
        return "SNAP"

    assert shared_statcast_snapshot(fetch=flaky, now=AS_OF) == ("SNAP", None)
    assert calls["n"] == 2

    def down(*, now):
        raise StatcastSourceError("STATCAST_FETCH_FAILED:TimeoutError:t")

    snap, reason = shared_statcast_snapshot(fetch=down, now=AS_OF)
    assert snap is None and reason.startswith("STATCAST_FETCH_FAILED")
