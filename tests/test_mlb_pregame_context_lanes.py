from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsedge.mlb_dk_hybrid_source import MLBDKHybridSourceError, acquire_dk_hybrid_quotes
from sportsedge.mlb_park_venue_source import acquire_park_venue_context
from sportsedge.mlb_weather_roof_source import acquire_weather_roof_context


NOW = datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)


def _venue_payload():
    return {
        "venues": [{
            "id": 3313,
            "name": "Example Park",
            "location": {
                "city": "Example",
                "stateAbbrev": "IL",
                "country": "USA",
                "defaultCoordinates": {"latitude": 41.95, "longitude": -87.65},
            },
            "timeZone": {"id": "America/Chicago"},
            "fieldInfo": {
                "roofType": "Open",
                "turfType": "Grass",
                "capacity": 41000,
                "leftLine": 355,
                "center": 400,
                "rightLine": 353,
            },
        }]
    }


def test_park_venue_binds_static_context_without_model_p():
    live = {"gameData": {"venue": {"id": 3313}}}
    result = acquire_park_venue_context(
        game_pk=1,
        as_of=NOW,
        live_payload=live,
        venue_payload=_venue_payload(),
    )
    assert result["status"] == "AVAILABLE"
    assert result["venue"]["venue_id"] == 3313
    assert result["venue"]["latitude"] == 41.95
    assert result["venue"]["roof_type"] == "Open"
    assert result["model_p_eligible"] is False


def test_weather_selects_nearest_hour_and_does_not_guess_roof_state():
    park = acquire_park_venue_context(
        game_pk=1,
        as_of=NOW,
        live_payload={"gameData": {"venue": {"id": 3313}}},
        venue_payload=_venue_payload(),
    )
    live = {"gameData": {"datetime": {"dateTime": "2026-09-22T23:10:00Z"}}}
    points = {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/LOT/1,2/forecast/hourly"}}
    hourly = {"properties": {"periods": [
        {
            "startTime": "2026-09-22T22:00:00+00:00",
            "temperature": 70,
            "temperatureUnit": "F",
            "windSpeed": "8 mph",
            "windDirection": "SW",
            "probabilityOfPrecipitation": {"value": 10},
            "shortForecast": "Mostly Clear",
            "isDaytime": False,
        },
        {
            "startTime": "2026-09-22T23:00:00+00:00",
            "temperature": 68,
            "temperatureUnit": "F",
            "windSpeed": "7 mph",
            "windDirection": "SW",
            "probabilityOfPrecipitation": {"value": 15},
            "shortForecast": "Clear",
            "isDaytime": False,
        },
    ]}}
    result = acquire_weather_roof_context(
        game_pk=1,
        as_of=NOW,
        park_venue=park,
        live_payload=live,
        points_payload=points,
        hourly_payload=hourly,
    )
    assert result["status"] == "AVAILABLE"
    assert result["forecast"]["start_time"] == "2026-09-22T23:00:00+00:00"
    assert result["forecast"]["precip_probability_pct"] == 15
    assert result["roof_type"] == "Open"
    assert result["roof_state"] == "UNKNOWN"
    assert result["model_p_eligible"] is False


def test_weather_fails_closed_without_coordinates():
    result = acquire_weather_roof_context(
        game_pk=1,
        as_of=NOW,
        park_venue={"venue": {"venue_id": 3313, "roof_type": "Retractable"}},
    )
    assert result["status"] == "UNAVAILABLE_NO_COORDINATES"
    assert result["forecast"] is None
    assert result["roof_state"] == "UNKNOWN"


def test_native_dk_missing_timestamp_is_intake_stamped_not_evidence():
    result = acquire_dk_hybrid_quotes(
        as_of=NOW,
        quotes=[{
            "game_id": "1",
            "market": "ML",
            "side": "HOME",
            "american_odds": -120,
            "sportsbook": "DraftKings",
        }],
    )
    row = result["quotes"][0]
    assert row["retrieved_at"] == NOW.isoformat()
    assert row["timestamp_source"] == "INTAKE_STAMPED"
    assert row["book_key"] == "draftkings_manual"
    assert row["sportsbook"] == "DraftKings"
    assert row["evidence_eligible"] is False
    assert row["model_p_eligible"] is False


def test_native_dk_provided_timestamp_is_preserved():
    result = acquire_dk_hybrid_quotes(
        as_of=NOW,
        quotes=[{
            "game_id": "1",
            "market": "TOTAL",
            "side": "OVER",
            "line": 8.5,
            "american_odds": -105,
            "retrieved_at": "2026-09-22T19:58:00+00:00",
            "book_key": "draftkings",
        }],
    )
    row = result["quotes"][0]
    assert row["retrieved_at"] == "2026-09-22T19:58:00+00:00"
    assert row["timestamp_source"] == "PROVIDED"
    assert result["provided_timestamp_count"] == 1


def test_native_dk_rejects_other_books():
    with pytest.raises(MLBDKHybridSourceError, match="NON_DRAFTKINGS_QUOTE_REJECTED"):
        acquire_dk_hybrid_quotes(
            as_of=NOW,
            quotes=[{"market": "ML", "american_odds": -110, "sportsbook": "FanDuel"}],
        )
