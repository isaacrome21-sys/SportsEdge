import json
import unittest

from sportsedge.sports.nfl.real_history_audit import audit_nfl_history_rows


class NFLRealHistoryAuditTests(unittest.TestCase):
    def test_audit_requires_multiseason_real_source_and_reports_key_number_pmf(self):
        rows = [
            {"season": 2022, "game_type": "REG", "home_score": 24, "away_score": 21, "spread_line": -3.0, "total_line": 45.5},
            {"season": 2022, "game_type": "REG", "home_score": 27, "away_score": 20, "spread_line": -6.5, "total_line": 47.0},
            {"season": 2023, "game_type": "REG", "home_score": 17, "away_score": 20, "spread_line": 2.5, "total_line": 41.0},
            {"season": 2023, "game_type": "REG", "home_score": 31, "away_score": 24, "spread_line": -7.0, "total_line": 48.5},
        ]
        report = audit_nfl_history_rows(
            rows,
            source_url="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
            source_sha256="a" * 64,
        )
        self.assertEqual(report["provenance"], "REAL_PUBLIC_HISTORY")
        self.assertEqual(report["seasons"], [2022, 2023])
        self.assertEqual(report["row_count"], 4)
        self.assertEqual(report["margin_pmf"]["3"], 0.5)
        self.assertEqual(report["margin_pmf"]["7"], 0.5)
        self.assertEqual(report["line_null_rates"]["spread_line"], 0.0)
        self.assertEqual(report["line_null_rates"]["total_line"], 0.0)
        json.dumps(report, sort_keys=True)

    def test_audit_rejects_fixture_provenance_and_single_season(self):
        rows = [{"season": 2023, "game_type": "REG", "home_score": 20, "away_score": 17, "spread_line": -3.0, "total_line": 44.0}]
        with self.assertRaisesRegex(ValueError, "REAL_HISTORY_REQUIRES_MULTIPLE_SEASONS"):
            audit_nfl_history_rows(rows, source_url="https://example.com/fixture.csv", source_sha256="b" * 64)

    def test_audit_rejects_invalid_source_hash(self):
        rows = [
            {"season": 2022, "game_type": "REG", "home_score": 20, "away_score": 17, "spread_line": -3.0, "total_line": 44.0},
            {"season": 2023, "game_type": "REG", "home_score": 24, "away_score": 17, "spread_line": -7.0, "total_line": 45.0},
        ]
        with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_INVALID"):
            audit_nfl_history_rows(rows, source_url="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv", source_sha256="bad")


if __name__ == "__main__":
    unittest.main()
