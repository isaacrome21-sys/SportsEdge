from __future__ import annotations

from datetime import datetime, timezone
import json

from sportsedge.mlb_run_it_pregame import acquire_mlb_run_it_pregame
from sportsedge.statcast_daily_source import StatcastSnapshot


class _Response:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


def test_bundle_resolves_cli_import_and_keeps_all_context_out_of_model_p():
    live_payload = {
        "gameData": {
            "datetime": {
                "officialDate": "2026-09-22",
                "dateTime": "2026-09-22T23:10:00Z",
            },
            "venue": {"id": 3313},
            "teams": {"away": {"id": 10}, "home": {"id": 20}},
            "probablePitchers": {
                "away": {"id": 501, "fullName": "Away Starter"},
                "home": {"id": 502, "fullName": "Home Starter"},
            },
        },
        "liveData": {
            "boxscore": {
                "officials": [
                    {"official": {"id": 77, "fullName": "HP Ump"}, "officialType": "Home Plate"}
                ],
                "teams": {
                    "away": {"battingOrder": [101, 102, 103]},
                    "home": {"battingOrder": [201, 202, 203]},
                },
            }
        },
    }
    snapshot = StatcastSnapshot(
        start_date="2026-08-23",
        end_date="2026-09-21",
        retrieved_at="2026-09-22T15:00:00+00:00",
        source="BASEBALL_SAVANT_STATCAST",
        batter_rows=(),
        pitcher_rows=(
            {"entity_id": "501", "pa": 100, "window_start": "2026-08-23", "window_end": "2026-09-21"},
            {"entity_id": "502", "pa": 100, "window_start": "2026-08-23", "window_end": "2026-09-21"},
        ),
        raw_pitch_rows=200,
    )
    prior_config = {
        "schema_version": "mlb_umpire_prior_test_v1",
        "league_prior": {
            "runs_per_game": 8.9,
            "strikeouts_per_game": 16.72,
            "walks_per_game": 6.32,
        },
        "prior_equivalent_games": 8,
        "min_home_plate_games": 8,
        "history_days": 365,
    }
    venue_payload = {
        "venues": [{
            "id": 3313,
            "name": "Example Park",
            "location": {
                "city": "Example",
                "stateAbbrev": "IL",
                "country": "USA",
                "latitude": 41.95,
                "longitude": -87.65,
            },
            "timeZone": {"id": "America/Chicago"},
            "fieldInfo": {"roofType": "Open", "turfType": "Grass", "capacity": 41000},
        }]
    }
    points_payload = {
        "properties": {"forecastHourly": "https://api.weather.gov/gridpoints/LOT/1,2/forecast/hourly"}
    }
    hourly_payload = {
        "properties": {"periods": [{
            "startTime": "2026-09-22T23:00:00+00:00",
            "temperature": 68,
            "temperatureUnit": "F",
            "windSpeed": "7 mph",
            "windDirection": "SW",
            "probabilityOfPrecipitation": {"value": 15},
            "shortForecast": "Clear",
            "isDaytime": False,
        }]}
    }

    def opener(req, timeout=30):
        url = getattr(req, "full_url", str(req))
        if "/roster?" in url:
            return _Response({"roster": []})
        if "/transactions?" in url:
            return _Response({"transactions": []})
        raise AssertionError(f"unexpected network request: {url}")

    bundle = acquire_mlb_run_it_pregame(
        game_pk=999005,
        as_of=datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc),
        opener=opener,
        live_payload=live_payload,
        statcast_snapshot=snapshot,
        umpire_history_rows=[],
        umpire_prior_config=prior_config,
        venue_payload=venue_payload,
        nws_points_payload=points_payload,
        nws_hourly_payload=hourly_payload,
        dk_quotes=[{
            "game_id": "999005",
            "market": "ML",
            "side": "HOME",
            "american_odds": -120,
            "sportsbook": "DraftKings",
        }],
    )

    assert bundle["model_p_eligible"] is False
    assert bundle["starters"]["model_p_eligible"] is False
    assert bundle["lineups"]["model_p_eligible"] is False
    assert bundle["injuries_scratches"]["model_p_eligible"] is False
    assert bundle["umpire"]["model_p_eligible"] is False
    assert bundle["statcast"]["model_p_eligible"] is False
    assert bundle["park_venue"]["model_p_eligible"] is False
    assert bundle["weather_roof"]["model_p_eligible"] is False
    assert bundle["hybrid_dk"]["model_p_eligible"] is False
    assert bundle["hybrid_dk"]["evidence_eligible"] is False
    assert bundle["hybrid_dk"]["quotes"][0]["timestamp_source"] == "INTAKE_STAMPED"
    assert bundle["statcast"]["preview"]["status"] == "SKIPPED"
    assert bundle["weather_roof"]["forecast"]["temperature"] == 68
    assert bundle["unimplemented_lanes"] == []
