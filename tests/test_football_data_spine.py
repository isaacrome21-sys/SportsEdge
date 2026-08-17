import unittest
from datetime import datetime, timezone


class FootballDataSpineTests(unittest.TestCase):
    def test_nfl_history_normalizes_lines_and_reports_null_rates(self):
        from sportsedge.sports.nfl.history import normalize_nfl_rows, null_rates

        rows = [
            {"game_id": "2025_01_A_B", "season": "2025", "game_type": "REG", "week": "1", "spread_line": "-3.5", "total_line": "45.5"},
            {"game_id": "2025_02_C_D", "season": "2025", "game_type": "REG", "week": "2", "spread_line": "", "total_line": "44"},
        ]
        out = normalize_nfl_rows(rows, seasons=[2025])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["spread_line"], -3.5)
        self.assertEqual(out[0]["total_line"], 45.5)
        rates = null_rates(out, ["spread_line", "total_line"])
        self.assertEqual(rates["spread_line"], 0.5)
        self.assertEqual(rates["total_line"], 0.0)

    def test_cfb_bulk_ingestion_stays_under_call_budget(self):
        from sportsedge.sports.cfb.history import CFBHistoryIngestor

        calls = []
        def fetch_json(endpoint, season):
            calls.append((endpoint, season))
            if endpoint == "games":
                return [{"id": season * 10 + 1, "season": season, "week": 1, "home_team": "A", "away_team": "B"}]
            if endpoint == "lines":
                return [{"id": season * 10 + 1, "season": season, "week": 1, "lines": [{"provider": "consensus", "spread": -3.0, "overUnder": 50.5}]}]
            raise AssertionError(endpoint)

        ingestor = CFBHistoryIngestor(fetch_json=fetch_json, max_calls=100)
        rows = ingestor.load(range(2013, 2026))
        self.assertLessEqual(ingestor.call_count, 100)
        self.assertEqual(ingestor.call_count, 26)
        self.assertEqual(len(rows), 26)

    def test_feature_asof_leakage_is_rejected(self):
        from sportsedge.core.leakage import assert_feature_asof_before_game

        good = {"feature_asof_ts": "2025-09-01T12:00:00+00:00", "game_start_ts": "2025-09-01T20:00:00+00:00"}
        assert_feature_asof_before_game([good])

        leaked = {"feature_asof_ts": "2025-09-01T20:00:00+00:00", "game_start_ts": "2025-09-01T20:00:00+00:00"}
        with self.assertRaises(ValueError):
            assert_feature_asof_before_game([leaked])


if __name__ == "__main__":
    unittest.main()
