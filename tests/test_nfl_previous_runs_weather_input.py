"""Fake-fetcher research weather receipts: no live requests, no pricing impact."""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.previous_runs_weather_input import (
    WeatherInputError, capture_nfl_weather,
)
from sportsedge.open_meteo_previous_runs import VARIABLES

KICKOFF = datetime(2026, 10, 25, 17, 25, tzinfo=timezone.utc)
DECISION = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
FETCHED = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def _blob(*, missing=None, null=None):
    hourly = {"time": ["2026-10-25T17:00"]}
    for variable in VARIABLES:
        if variable != missing:
            hourly[f"{variable}_previous_day1"] = [None if variable == null else 8.0]
    return json.dumps({"hourly": hourly}).encode("utf-8")


def _run(raw=None, **changes):
    raw = _blob() if raw is None else raw
    kw = dict(game_id="2026_08_PIT_NO", kickoff=KICKOFF, decision_at=DECISION,
              latitude=29.95, longitude=-90.08, lead_days=1,
              fetch=lambda _: raw, clock=lambda: FETCHED)
    kw.update(changes)
    return capture_nfl_weather(**kw)


def test_fixture_weather_receipt_is_hash_bound_nonpricing():
    raw = _blob()
    row = _run(raw)
    assert row["game_id"] == "2026_08_PIT_NO"
    assert row["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert row["forecast_valid_hour_utc"] == "2026-10-25T17:00:00+00:00"
    assert row["available_no_later_than_utc"] == "2026-10-24T17:00:00+00:00"
    assert row["source_url"].startswith("https://previous-runs-api.open-meteo.com/v1/forecast?")
    assert row["historical_pit"] is False and row["pricing_input"] is False
    assert row["play_eligible"] is False
    assert row["weather"]["wind_mph"] == 8.0
    assert row["attribution"] == "Open-Meteo, CC BY 4.0"


@pytest.mark.parametrize("changes, code", [
    ({"game_id": ""}, "GAME_ID_REQUIRED"),
    ({"kickoff": "2026-10-25T17:25:00"}, "KICKOFF_OFFSET_REQUIRED"),
    ({"decision_at": "2026-10-25T15:00:00"}, "DECISION_OFFSET_REQUIRED"),
    ({"decision_at": KICKOFF}, "DECISION_NOT_PREGAME"),
    ({"decision_at": datetime(2026, 10, 24, 16, tzinfo=timezone.utc)}, "LEAD_TOO_SHORT_FOR_DECISION"),
    ({"latitude": 91}, "COORDINATE_INVALID"),
    ({"clock": lambda: datetime(2026, 10, 24, 15, tzinfo=timezone.utc)}, "FETCH_BEFORE_FORECAST_AVAILABLE"),
])
def test_refuses_invalid_identity_asof_or_lead(changes, code):
    with pytest.raises(WeatherInputError, match=code):
        _run(**changes)


@pytest.mark.parametrize("raw, code", [
    (b"", "SOURCE_BYTES_INVALID"),
    (b"not-json", "SOURCE_REFUSED"),
    (json.dumps({"error": True}).encode(), "SOURCE_PAYLOAD_INVALID"),
    (_blob(missing="wind_gusts_10m"), "SERIES_MISSING"),
    (_blob(null="wind_speed_10m"), "WEATHER_INCOMPLETE"),
])
def test_refuses_broken_source_rows(raw, code):
    with pytest.raises(WeatherInputError, match=code):
        _run(raw)


def test_uses_exact_postfetch_clock_not_old_decision():
    row = _run()
    assert row["source_fetched_at_utc"] == FETCHED.isoformat()
    assert row["source_fetched_at_utc"] != row["decision_utc"]
