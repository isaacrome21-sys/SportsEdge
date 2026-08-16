import json
import unittest

from sportsedge.v7_distribution import simulate_game_distribution
from sportsedge.v7_shadow import V7ShadowError, evaluate_promotion, merge_shadow_rows
from sportsedge.v7_sources import (
    extract_home_plate_umpire, extract_starting_catcher_ids,
    fetch_mlb_schedule, fetch_nws_hourly, fetch_savant_statcast,
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
    def read(self):
        return self.payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class V7OperationalFinishTests(unittest.TestCase):
    def test_distribution_is_deterministic_and_coherent(self):
        a = simulate_game_distribution(away_mean_runs=4.1, home_mean_runs=4.7, total_line=8.5, simulations=5000, seed=91)
        b = simulate_game_distribution(away_mean_runs=4.1, home_mean_runs=4.7, total_line=8.5, simulations=5000, seed=91)
        self.assertEqual(a.result_sha256, b.result_sha256)
        self.assertAlmostEqual(a.home_win_probability + a.away_win_probability, 1.0)
        self.assertAlmostEqual(a.nrfi_probability + a.yrfi_probability, 1.0)
        self.assertAlmostEqual(a.over_probability + a.under_probability + a.push_probability, 1.0)
        self.assertGreater(a.home_win_probability, 0.5)

    def test_shadow_is_immutable_and_fail_closed(self):
        base = {
            "game_pk": 777, "market": "YRFI", "prediction_as_of": "2026-08-16T17:00:00Z",
            "candidate_probability": 0.48, "baseline_probability": 0.49,
            "candidate_sha256": "candidate", "feature_contract_sha256": "features",
        }
        rows = merge_shadow_rows([base, {**base, "outcome": 1, "outcome_source": "MLB_STATSAPI"}])
        self.assertEqual(rows[0]["outcome"], 1)
        with self.assertRaises(V7ShadowError):
            merge_shadow_rows([base, {**base, "candidate_probability": 0.55}])
        report = evaluate_promotion(rows, eligible_slate_games=1)
        self.assertFalse(report["eligible"])
        self.assertIn("MIN_UNIQUE_GAMES", report["reasons"])
        self.assertIn("MIN_CALENDAR_DAYS", report["reasons"])

    def test_schedule_and_savant_snapshots_hash_raw_payload(self):
        def opener(req, timeout=20):
            url = req.full_url
            if "statsapi" in url:
                return FakeResponse(b'{"dates":[]}')
            return FakeResponse(b'game_date,events\n2026-08-15,single\n')
        schedule = fetch_mlb_schedule("2026-08-16", opener=opener, retrieved_at="2026-08-16T15:00:00Z")
        savant = fetch_savant_statcast("2026-08-01", "2026-08-15", opener=opener, retrieved_at="2026-08-16T15:00:00Z")
        self.assertEqual(schedule.provider, "MLB_STATSAPI_SCHEDULE")
        self.assertEqual(savant.payload[0]["events"], "single")
        self.assertEqual(len(schedule.payload_sha256), 64)

    def test_nws_two_step_hourly(self):
        def opener(req, timeout=20):
            if "/points/" in req.full_url:
                return FakeResponse(json.dumps({"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/LOT/1,2/forecast/hourly"}}).encode())
            return FakeResponse(json.dumps({"properties": {"periods": [{"temperature": 80}]}}).encode())
        point, forecast = fetch_nws_hourly(41.9, -87.6, opener=opener, retrieved_at="2026-08-16T15:00:00Z")
        self.assertEqual(point.provider, "NWS_POINTS")
        self.assertEqual(forecast.payload["properties"]["periods"][0]["temperature"], 80)

    def test_live_feed_extractors(self):
        feed = {
            "liveData": {"boxscore": {
                "officials": [{"officialType": "Home Plate", "official": {"id": 9, "fullName": "Ump"}}],
                "teams": {
                    "away": {"battingOrder": [11], "players": {"ID11": {"person": {"id": 11}, "position": {"abbreviation": "C"}}}},
                    "home": {"battingOrder": [22], "players": {"ID22": {"person": {"id": 22}, "position": {"abbreviation": "C"}}}},
                },
            }}
        }
        self.assertEqual(extract_home_plate_umpire(feed)["umpire_id"], 9)
        self.assertEqual(extract_starting_catcher_ids(feed), {"away": 11, "home": 22})


if __name__ == "__main__":
    unittest.main()
