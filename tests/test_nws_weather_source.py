"""Offline coverage for the NWS game-window weather source.

Payloads are recorded from the live api.weather.gov probe of 2026-10-24
(Austin, TX grid EWX/156,92; KAUS observations around the Texas vs
Ole Miss kickoff, 2026-10-24T23:30:00Z), trimmed to the fields the API
returned. No network is touched.
"""
import unittest
from datetime import datetime, timezone

from sportsedge.nws_weather_source import (
    NWSWeatherSourceError, compass16, game_window_weather,
    normalize_forecast_periods,
)

UTC = timezone.utc
KICKOFF = datetime(2026, 10, 24, 23, 30, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
NOW = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)

POINTS = {
    "properties": {
        "cwa": "EWX",
        "gridId": "EWX",
        "gridX": 156,
        "gridY": 92,
        "forecast": "https://api.weather.gov/gridpoints/EWX/156,92/forecast",
        "forecastHourly":
            "https://api.weather.gov/gridpoints/EWX/156,92/forecast/hourly",
        "observationStations":
            "https://api.weather.gov/gridpoints/EWX/156,92/stations",
    }
}

STATIONS = {
    "features": [
        {"properties": {"stationIdentifier": "KATT",
                        "name": "Austin City Austin Camp Mabry"}},
        {"properties": {"stationIdentifier": "KAUS",
                        "name": "Austin-Bergstrom International Airport"}},
    ]
}


def _obs(ts, temp, dew, deg, kmh, text, precip=None):
    def q(unit, value):
        return {"unitCode": unit, "value": value, "qualityControl": "V"}
    return {"properties": {
        "timestamp": ts,
        "textDescription": text,
        "temperature": q("wmoUnit:degC", temp),
        "dewpoint": q("wmoUnit:degC", dew),
        "windDirection": q("wmoUnit:degree_(angle)", deg),
        "windSpeed": q("wmoUnit:km_h-1", kmh),
        "windGust": q("wmoUnit:km_h-1", None),
        "precipitationLastHour": q("wmoUnit:mm", precip),
    }}


# Recorded KAUS observations, 2026-10-24 (values verbatim from the probe).
KAUS_OBS = {"features": [
    _obs("2026-10-24T23:05:00+00:00", 29, 14, 130, 20.376, "Clear"),
    _obs("2026-10-24T23:25:00+00:00", 28, 14, 130, 18.504, "Clear"),
    _obs("2026-10-24T23:35:00+00:00", 28, 14, 130, 12.96, "Clear"),
    _obs("2026-10-24T23:40:00+00:00", 28, 14, 130, 14.832, "Mostly Clear"),
    _obs("2026-10-24T23:55:00+00:00", 27, 16, 110, 20.376, "Mostly Cloudy"),
]}

EMPTY = {"features": []}

# Recorded hourly forecast periods (Austin, issued 2026-10-24 evening CT).
HOURLY = {"properties": {"periods": [
    {"startTime": "2026-10-24T22:00:00-05:00",
     "endTime": "2026-10-24T23:00:00-05:00",
     "temperature": 74, "temperatureUnit": "F",
     "windSpeed": "5 mph", "windDirection": "SE",
     "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent",
                                     "value": 0},
     "shortForecast": "Mostly Cloudy"},
    {"startTime": "2026-10-24T23:00:00-05:00",
     "endTime": "2026-10-25T00:00:00-05:00",
     "temperature": 72, "temperatureUnit": "F",
     "windSpeed": "5 mph", "windDirection": "SE",
     "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent",
                                     "value": 0},
     "shortForecast": "Partly Cloudy"},
]}}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        import json
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Routes by URL substring; overrides map substring -> payload/Exception."""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def __call__(self, req, timeout=None):
        url = req.full_url
        for key, value in self.overrides.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return _Response(value)
        if "/points/" in url:
            return _Response(POINTS)
        if "/stations/KATT/observations" in url:
            return _Response(EMPTY)
        if "/stations/KAUS/observations" in url:
            return _Response(KAUS_OBS)
        if url.endswith("/stations"):
            return _Response(STATIONS)
        if "forecast/hourly" in url:
            return _Response(HOURLY)
        raise AssertionError(f"unexpected URL: {url}")


def collect(opener, start=KICKOFF, end=WINDOW_END, now=NOW):
    return game_window_weather(30.285, -97.732, window_start=start,
                               window_end=end, now=now, opener=opener)


class NWSWeatherSourceTests(unittest.TestCase):
    def test_kickoff_window_verified_from_recorded_kaus(self):
        record = collect(FakeOpener())
        self.assertEqual(record["status"], "VERIFIED_OBSERVATION")
        self.assertIsNone(record["status_reason"])
        self.assertEqual(record["provenance"]["stations_tried"],
                         ["KATT", "KAUS"])
        self.assertEqual(record["provenance"]["grid_id"], "EWX")
        obs = record["observation"]
        self.assertEqual(obs["station_id"], "KAUS")
        self.assertEqual(obs["observed_at"], "2026-10-24T23:35:00+00:00")
        self.assertEqual(obs["temperature_f"], 82.4)
        self.assertEqual(obs["wind_speed_mph"], 8.1)
        self.assertEqual(obs["wind_direction_degrees"], 130.0)
        self.assertEqual(obs["wind_compass"], "SE")
        self.assertEqual(obs["conditions"], "Clear")
        # Null precipitation is missing data, never zero.
        self.assertIsNone(obs["precipitation_last_hour_mm"])
        # Recorded hourly periods do not overlap this window.
        self.assertEqual(record["forecast_periods"], [])
        # Research-only labeling on the record's face.
        self.assertTrue(record["research_only"])
        self.assertEqual(record["pricing_impact"], "NONE")
        self.assertEqual(record["validation_status"], "PENDING_VALIDATION")
        self.assertFalse(record["staking_allowed"])

    def test_no_observation_in_window_unverified_with_forecast(self):
        start = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
        end = datetime(2026, 10, 25, 5, 0, tzinfo=UTC)
        record = collect(FakeOpener(), start=start, end=end,
                         now=datetime(2026, 10, 25, 5, 30, tzinfo=UTC))
        self.assertEqual(record["status"], "UNVERIFIED")
        self.assertEqual(record["status_reason"], "NO_OBSERVATION_IN_WINDOW")
        self.assertIsNone(record["observation"])
        self.assertEqual(len(record["forecast_periods"]), 2)
        first = record["forecast_periods"][0]
        self.assertEqual(first["temperature_f"], 74.0)
        self.assertEqual(first["wind_speed_mph"], 5.0)
        self.assertEqual(first["probability_of_precipitation_pct"], 0)

    def test_stale_observation_unverified(self):
        stale = {"features": [
            _obs("2026-10-25T02:00:00+00:00", 25, 14, 130, 10.0, "Clear")]}
        record = collect(FakeOpener({"/stations/KAUS/observations": stale}))
        self.assertEqual(record["status"], "UNVERIFIED")
        self.assertEqual(record["status_reason"],
                         "OBSERVATION_STALE_AT_WINDOW_START")
        self.assertIsNone(record["observation"])

    def test_future_observation_rejected(self):
        record = collect(FakeOpener(),
                         now=datetime(2026, 10, 24, 23, 32, tzinfo=UTC))
        self.assertEqual(record["status"], "UNVERIFIED")
        self.assertEqual(record["status_reason"], "NO_OBSERVATION_IN_WINDOW")

    def test_cursor_pages_walked_back_to_window_start(self):
        # Page 1 ends at 00:51Z (81 min after kickoff) but holds a cursor;
        # the 23:35Z report lives on page 2 and must win selection.
        page1 = {"features": [
            _obs("2026-10-25T01:55:00+00:00", 26, 16, 120, 14.832,
                 "Partly Cloudy"),
            _obs("2026-10-25T00:51:00+00:00", 26, 16, 120, 12.96,
                 "Partly Cloudy")],
            "pagination": {"next":
                "https://api.weather.gov/stations/KAUS/observations"
                "?cursor=PAGE2"}}
        page2 = {"features": [
            _obs("2026-10-24T23:35:00+00:00", 28, 14, 130, 12.96, "Clear")]}
        opener = FakeOpener({"cursor=PAGE2": page2,
                             "/stations/KAUS/observations": page1})
        record = collect(opener)
        self.assertEqual(record["status"], "VERIFIED_OBSERVATION")
        self.assertEqual(record["observation"]["observed_at"],
                         "2026-10-24T23:35:00+00:00")

    def test_precipitation_value_passes_through(self):
        wet = {"features": [
            _obs("2026-10-24T23:35:00+00:00", 28, 14, 130, 12.96, "Rain",
                 precip=2.5)]}
        record = collect(FakeOpener({"/stations/KAUS/observations": wet}))
        self.assertEqual(record["status"], "VERIFIED_OBSERVATION")
        self.assertEqual(
            record["observation"]["precipitation_last_hour_mm"], 2.5)

    def test_wrong_unit_temperature_treated_missing(self):
        odd = _obs("2026-10-24T23:35:00+00:00", 28, 14, 130, 12.96, "Clear")
        odd["properties"]["temperature"] = {
            "unitCode": "wmoUnit:degF", "value": 82, "qualityControl": "V"}
        record = collect(FakeOpener(
            {"/stations/KAUS/observations": {"features": [odd]}}))
        self.assertEqual(record["status"], "VERIFIED_OBSERVATION")
        self.assertIsNone(record["observation"]["temperature_f"])
        self.assertEqual(record["observation"]["wind_speed_mph"], 8.1)

    def test_points_transport_failure_raises(self):
        with self.assertRaises(NWSWeatherSourceError):
            collect(FakeOpener({"/points/": OSError("down")}))

    def test_naive_window_rejected(self):
        with self.assertRaises(NWSWeatherSourceError):
            collect(FakeOpener(), start=datetime(2026, 10, 24, 23, 30))

    def test_compass_boundaries(self):
        self.assertEqual(compass16(0), "N")
        self.assertEqual(compass16(359), "N")
        self.assertEqual(compass16(90), "E")
        self.assertEqual(compass16(130), "SE")
        self.assertEqual(compass16(180), "S")
        self.assertEqual(compass16(270), "W")
        self.assertIsNone(compass16(None))

    def test_forecast_wind_range_takes_max(self):
        payload = {"properties": {"periods": [
            {"startTime": "2026-10-24T23:00:00+00:00",
             "endTime": "2026-10-25T00:00:00+00:00",
             "temperature": 80, "temperatureUnit": "F",
             "windSpeed": "5 to 10 mph", "windDirection": "SE",
             "probabilityOfPrecipitation": {"value": 20},
             "shortForecast": "Clear"}]}}
        periods = normalize_forecast_periods(
            payload, window_start=KICKOFF, window_end=WINDOW_END)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["wind_speed_mph"], 10.0)


if __name__ == "__main__":
    unittest.main()
