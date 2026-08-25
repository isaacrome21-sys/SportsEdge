import hashlib
import unittest


class NFLEnvironmentProfileTests(unittest.TestCase):
    def _rows(self):
        return [
            {"season": 2023, "game_type": "REG", "home_score": 24, "away_score": 20, "neutral_site": False},
            {"season": 2023, "game_type": "REG", "home_score": 17, "away_score": 21, "neutral_site": False},
            {"season": 2024, "game_type": "REG", "home_score": 30, "away_score": 20, "neutral_site": False},
            {"season": 2024, "game_type": "REG", "home_score": 20, "away_score": 20, "neutral_site": True},
        ]

    def _sha(self):
        return hashlib.sha256(b"nfl-environment-fixture").hexdigest()

    def test_profile_is_real_history_hash_bound_and_multi_season(self):
        from sportsedge.sports.nfl.environment_profile import fit_nfl_environment_profile

        profile = fit_nfl_environment_profile(
            self._rows(),
            source_url="https://example.invalid/nfl.csv",
            source_sha256=self._sha(),
            min_games=4,
        )
        self.assertEqual(profile["provenance"], "REAL_PUBLIC_HISTORY")
        self.assertEqual(profile["source_sha256"], self._sha())
        self.assertEqual(profile["seasons"], [2023, 2024])
        self.assertEqual(profile["game_count"], 4)
        self.assertEqual(profile["non_neutral_game_count"], 3)
        self.assertAlmostEqual(profile["hfa_points"], (4 - 4 + 10) / 3)
        self.assertGreater(profile["margin_sigma"], 0)
        self.assertGreater(profile["total_sigma"], 0)

    def test_neutral_games_do_not_contribute_to_hfa(self):
        from sportsedge.sports.nfl.environment_profile import fit_nfl_environment_profile

        rows = self._rows() + [
            {"season": 2024, "game_type": "REG", "home_score": 60, "away_score": 0, "neutral_site": True},
        ]
        profile = fit_nfl_environment_profile(
            rows,
            source_url="https://example.invalid/nfl.csv",
            source_sha256=self._sha(),
            min_games=5,
        )
        self.assertAlmostEqual(profile["hfa_points"], (4 - 4 + 10) / 3)

    def test_profile_requires_multiple_seasons_enough_games_and_valid_hash(self):
        from sportsedge.sports.nfl.environment_profile import fit_nfl_environment_profile

        with self.assertRaisesRegex(ValueError, "MULTI_SEASON_HISTORY_REQUIRED"):
            fit_nfl_environment_profile(
                [row for row in self._rows() if row["season"] == 2023],
                source_url="https://example.invalid/nfl.csv",
                source_sha256=self._sha(),
                min_games=2,
            )
        with self.assertRaisesRegex(ValueError, "NFL_ENVIRONMENT_MIN_GAMES_NOT_MET"):
            fit_nfl_environment_profile(
                self._rows(),
                source_url="https://example.invalid/nfl.csv",
                source_sha256=self._sha(),
                min_games=5,
            )
        with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_INVALID"):
            fit_nfl_environment_profile(
                self._rows(),
                source_url="https://example.invalid/nfl.csv",
                source_sha256="bad",
                min_games=4,
            )

    def test_missing_scores_and_non_regular_rows_are_excluded_but_accounted(self):
        from sportsedge.sports.nfl.environment_profile import fit_nfl_environment_profile

        rows = self._rows() + [
            {"season": 2024, "game_type": "PRE", "home_score": 40, "away_score": 0},
            {"season": 2024, "game_type": "REG", "home_score": None, "away_score": 10},
        ]
        profile = fit_nfl_environment_profile(
            rows,
            source_url="https://example.invalid/nfl.csv",
            source_sha256=self._sha(),
            min_games=4,
        )
        self.assertEqual(profile["input_row_count"], 6)
        self.assertEqual(profile["game_count"], 4)
        self.assertEqual(profile["excluded_row_count"], 2)

    def test_adapter_consumes_profile_for_sigma_and_hfa_and_neutral_is_zero(self):
        from sportsedge.sports.nfl.adapter import NFLAdapter
        from sportsedge.sports.nfl.environment_profile import fit_nfl_environment_profile

        profile = fit_nfl_environment_profile(
            self._rows(),
            source_url="https://example.invalid/nfl.csv",
            source_sha256=self._sha(),
            min_games=4,
        )
        adapter = NFLAdapter(environment_profile=profile)
        self.assertEqual(adapter.margin_sigma({}), profile["margin_sigma"])
        self.assertEqual(adapter.total_sigma({}), profile["total_sigma"])
        self.assertEqual(adapter.hfa_prior(None, {}), profile["hfa_points"])
        self.assertEqual(adapter.hfa_prior(None, {"neutral_site": True}), 0.0)

    def test_adapter_fails_closed_without_profile(self):
        from sportsedge.sports.nfl.adapter import NFLAdapter

        adapter = NFLAdapter()
        with self.assertRaisesRegex(ValueError, "NFL_ENVIRONMENT_PROFILE_REQUIRED"):
            adapter.margin_sigma({})
        with self.assertRaisesRegex(ValueError, "NFL_ENVIRONMENT_PROFILE_REQUIRED"):
            adapter.total_sigma({})
        with self.assertRaisesRegex(ValueError, "NFL_ENVIRONMENT_PROFILE_REQUIRED"):
            adapter.hfa_prior(None, {})

    def test_historical_key_numbers_are_validation_targets_not_simulator_inputs(self):
        from sportsedge.sports.nfl.adapter import NFLAdapter

        simulator_profile = {
            "key_number_contract": "EMERGENT_VALIDATION_TARGET_V1",
            "validation_target_key_frequency": {-7: 0.05, -3: 0.08, 3: 0.09, 7: 0.06},
        }
        adapter = NFLAdapter(simulator_profile=simulator_profile)
        self.assertEqual(
            adapter.key_number_validation_targets(),
            {-7: 0.05, -3: 0.08, 3: 0.09, 7: 0.06},
        )
        with self.assertRaisesRegex(ValueError, "HISTORICAL_KEY_NUMBERS_ARE_VALIDATION_ONLY"):
            adapter.key_numbers()


if __name__ == "__main__":
    unittest.main()
