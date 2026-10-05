import unittest

from scripts import research_mlb_f5_nrfi_tightening as RESEARCH
from sportsedge.f5_distribution import (
    F5DistributionError,
    build_f5_distribution,
    read_f5_probability,
)
from sportsedge.shared_f5_engine import build_shared_f5_engine_session


FEATURES = {
    "away_f5_runs_for": [0, 1, 2, 3, 1, 0, 4, 2, 1, 3],
    "away_f5_runs_against": [1, 2, 1, 0, 3, 2, 2, 4, 0, 1],
    "home_f5_runs_for": [2, 1, 3, 0, 2, 4, 1, 2, 3, 1],
    "home_f5_runs_against": [0, 2, 1, 3, 1, 2, 4, 1, 2, 0],
    "league_f5_pmf": {"0": 0.20, "1": 0.25, "2": 0.25, "3": 0.15, "4": 0.10, "5": 0.05},
    "league_prior_halves": 1000,
    "league_prior_strength": 30,
}


class F5DistributionTests(unittest.TestCase):
    def test_joint_distribution_conserves_probability(self):
        distribution = build_f5_distribution(FEATURES, league_prior_strength=30)
        self.assertAlmostEqual(sum(distribution.joint_score_pmf.values()), 1.0, places=12)

    def test_moneyline_preserves_f5_tie_as_push(self):
        distribution = build_f5_distribution(FEATURES, league_prior_strength=30)
        home = read_f5_probability(distribution, market="F5_MONEYLINE", side="HOME")
        away = read_f5_probability(distribution, market="F5_MONEYLINE", side="AWAY")
        self.assertAlmostEqual(
            home.probability + away.probability + home.push_probability,
            1.0,
            places=12,
        )
        self.assertAlmostEqual(home.push_probability, away.push_probability, places=12)
        self.assertGreater(home.push_probability, 0.0)

    def test_integer_total_and_team_total_preserve_push_mass(self):
        distribution = build_f5_distribution(FEATURES, league_prior_strength=30)
        over = read_f5_probability(distribution, market="F5_TOTALS", line=4.0, side="OVER")
        under = read_f5_probability(distribution, market="F5_TOTALS", line=4.0, side="UNDER")
        self.assertAlmostEqual(
            over.probability + under.probability + over.push_probability,
            1.0,
            places=12,
        )
        team_over = read_f5_probability(
            distribution,
            market="F5_TEAM_TOTALS",
            line=2.0,
            side="OVER",
            team_side="HOME",
        )
        team_under = read_f5_probability(
            distribution,
            market="F5_TEAM_TOTALS",
            line=2.0,
            side="UNDER",
            team_side="HOME",
        )
        self.assertAlmostEqual(
            team_over.probability + team_under.probability + team_over.push_probability,
            1.0,
            places=12,
        )

    def test_sparse_empirical_certainty_is_shrunk(self):
        zero = dict(FEATURES)
        for key in (
            "away_f5_runs_for", "away_f5_runs_against",
            "home_f5_runs_for", "home_f5_runs_against",
        ):
            zero[key] = [0] * 10
        distribution = build_f5_distribution(zero, league_prior_strength=30)
        home = read_f5_probability(distribution, market="F5_MONEYLINE", side="HOME")
        total_over = read_f5_probability(
            distribution, market="F5_TOTALS", line=0.5, side="OVER"
        )
        self.assertGreater(home.probability, 0.0)
        self.assertLess(home.push_probability, 1.0)
        self.assertGreater(total_over.probability, 0.0)
        self.assertLess(total_over.probability, 1.0)

    def test_default_builder_preserves_legacy_empirical_mode_for_unrelated_consumers(self):
        legacy_features = {
            key: value for key, value in FEATURES.items()
            if not key.startswith("league_")
        }
        distribution = build_f5_distribution(legacy_features)
        self.assertEqual(distribution.distribution_version, "mlb_f5_empirical_state_v1_candidate")
        self.assertAlmostEqual(sum(distribution.joint_score_pmf.values()), 1.0, places=12)

    def test_m30_league_prior_exact_distribution_math(self):
        features = {
            "away_f5_runs_for": [0] * 10,
            "away_f5_runs_against": [0] * 10,
            "home_f5_runs_for": [0] * 10,
            "home_f5_runs_against": [0] * 10,
            "league_f5_pmf": {"0": 0.5, "1": 0.5},
            "league_prior_halves": 1000,
            "league_prior_strength": 30,
        }
        distribution = build_f5_distribution(features, league_prior_strength=30)
        # Each smoothed marginal is p(0)=(10+30*.5)/40=.625 and p(1)=.375.
        self.assertAlmostEqual(distribution.joint_score_pmf["0,0"], 0.625 * 0.625, places=12)
        self.assertAlmostEqual(distribution.joint_score_pmf["1,1"], 0.375 * 0.375, places=12)
        self.assertAlmostEqual(sum(distribution.joint_score_pmf.values()), 1.0, places=12)

    def test_distribution_matches_winning_research_m30_recipe(self):
        distribution = build_f5_distribution(FEATURES, league_prior_strength=30)
        league = {int(k): float(v) for k, v in FEATURES["league_f5_pmf"].items()}
        away = RESEARCH.blend(
            RESEARCH.smoothed_pmf(FEATURES["away_f5_runs_for"], league, 30),
            RESEARCH.smoothed_pmf(FEATURES["home_f5_runs_against"], league, 30),
        )
        home = RESEARCH.blend(
            RESEARCH.smoothed_pmf(FEATURES["home_f5_runs_for"], league, 30),
            RESEARCH.smoothed_pmf(FEATURES["away_f5_runs_against"], league, 30),
        )
        expected = {
            f"{ar},{hr}": ap * hp
            for ar, ap in sorted(away.items())
            for hr, hp in sorted(home.items())
        }
        self.assertEqual(set(distribution.joint_score_pmf), set(expected))
        for key, probability in expected.items():
            self.assertAlmostEqual(
                distribution.joint_score_pmf[key], probability, places=12
            )

    def test_league_prior_identity_fails_closed(self):
        bad = dict(FEATURES)
        bad["league_prior_strength"] = 15
        with self.assertRaises(F5DistributionError):
            build_f5_distribution(bad, league_prior_strength=30)
        bad = dict(FEATURES)
        bad["league_prior_halves"] = 199
        with self.assertRaises(F5DistributionError):
            build_f5_distribution(bad, league_prior_strength=30)

    def test_history_floor_fails_closed(self):
        bad = dict(FEATURES)
        bad["away_f5_runs_for"] = [1] * 9
        with self.assertRaises(F5DistributionError):
            build_f5_distribution(bad, league_prior_strength=30)

    def test_one_session_reuses_one_distribution_for_all_four_markets(self):
        calls = []

        def builder(features):
            calls.append(1)
            return build_f5_distribution(features, league_prior_strength=30)

        engine = build_shared_f5_engine_session(builder=builder)
        base = {
            "game_id": "g1",
            "entity_id": "g1",
            "features": FEATURES,
            "feature_source_hash": "a" * 64,
        }
        rows = [
            engine({**base, "market": "F5_MONEYLINE", "side": "HOME", "line": 0.0}),
            engine({**base, "market": "F5_RUN_LINE", "side": "HOME", "line": -0.5}),
            engine({**base, "market": "F5_TOTALS", "side": "OVER", "line": 4.5}),
            engine({**base, "entity_id": "20", "team_side": "HOME", "market": "F5_TEAM_TOTALS", "side": "OVER", "line": 2.5}),
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({row["model_input_hash"] for row in rows}), 1)
        self.assertEqual(len({row["distribution_sha256"] for row in rows}), 1)
        self.assertEqual(len({row["readout_sha256"] for row in rows}), 4)
        self.assertTrue(all(row["mc_paths"] == 0 for row in rows))


if __name__ == "__main__":
    unittest.main()
