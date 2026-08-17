import unittest

from sportsedge.core.validation.football_evidence import (
    FootballValidationBundle,
    build_promotion_evidence,
    validate_real_history_bundle,
)


class FootballRealValidationTests(unittest.TestCase):
    def test_synthetic_or_fixture_history_cannot_promote(self):
        bundle = FootballValidationBundle(
            sport="nfl",
            provenance="fixture",
            source_uri="tests/fixtures/nfl.json",
            source_sha256="a" * 64,
            rows=[{"season": 2024, "market": "spread", "m1_log_loss": 0.69, "m2_log_loss": 0.68}],
        )
        with self.assertRaisesRegex(ValueError, "REAL_HISTORY_REQUIRED"):
            validate_real_history_bundle(bundle)

    def test_real_history_requires_hash_source_and_multiple_seasons(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_REQUIRED"):
            validate_real_history_bundle(FootballValidationBundle("cfb", "real", "cfbd://lines", "", []))

        one_season = FootballValidationBundle(
            "cfb", "real", "cfbd://lines", "b" * 64,
            [{"season": 2024, "market": "spread", "m1_log_loss": 0.69, "m2_log_loss": 0.68}],
        )
        with self.assertRaisesRegex(ValueError, "INSUFFICIENT_WALKFORWARD_SEASONS"):
            validate_real_history_bundle(one_season)

    def test_promotion_evidence_is_per_market_and_uses_fold_win_rate(self):
        rows = []
        for season in range(2019, 2025):
            rows.append({"season": season, "market": "spread", "m1_log_loss": 0.69, "m2_log_loss": 0.67})
            rows.append({"season": season, "market": "total", "m1_log_loss": 0.68, "m2_log_loss": 0.69})
        bundle = FootballValidationBundle("nfl", "real", "nflverse://games", "c" * 64, rows)
        validated = validate_real_history_bundle(bundle)
        evidence = build_promotion_evidence(validated)
        self.assertGreaterEqual(evidence["spread"].fold_win_rate, 0.65)
        self.assertLess(evidence["total"].fold_win_rate, 0.65)
        self.assertEqual(evidence["spread"].sport, "nfl")


if __name__ == "__main__":
    unittest.main()
