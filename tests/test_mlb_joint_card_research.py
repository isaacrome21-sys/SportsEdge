import unittest

from sportsedge.mlb_joint_card_research import simulate_joint_card
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import V7_DISTRIBUTION_VERSION, simulate_game_distribution


class TestMLBJointCardResearch(unittest.TestCase):
    def _pools(self):
        return {
            "away-p": [
                {"strikeouts": 8, "outs": 18, "earned_runs": 2, "hits_allowed": 4, "walks_allowed": 1},
                {"strikeouts": 7, "outs": 17, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2},
                {"strikeouts": 9, "outs": 19, "earned_runs": 1, "hits_allowed": 3, "walks_allowed": 1},
                {"strikeouts": 6, "outs": 16, "earned_runs": 3, "hits_allowed": 6, "walks_allowed": 2},
                {"strikeouts": 10, "outs": 20, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 0},
            ],
            "home-p": [
                {"strikeouts": 5, "outs": 14, "earned_runs": 4, "hits_allowed": 7, "walks_allowed": 3},
                {"strikeouts": 4, "outs": 15, "earned_runs": 3, "hits_allowed": 6, "walks_allowed": 2},
                {"strikeouts": 6, "outs": 16, "earned_runs": 4, "hits_allowed": 8, "walks_allowed": 2},
                {"strikeouts": 3, "outs": 13, "earned_runs": 5, "hits_allowed": 9, "walks_allowed": 4},
                {"strikeouts": 5, "outs": 15, "earned_runs": 3, "hits_allowed": 7, "walks_allowed": 3},
            ],
        }

    def _run(self):
        return simulate_joint_card(
            game_id="test-game",
            away_mean_runs=2.9,
            home_mean_runs=4.2,
            feature_source_hash="feature-hash",
            simulations=4000,
            pitcher_pools=self._pools(),
            selections=[
                {"selection_id": "home-ml", "market": "MONEYLINE", "side": "HOME", "line": 0},
                {"selection_id": "home-rl", "market": "RUN_LINE", "side": "HOME", "line": -1.5},
                {"selection_id": "over-6", "market": "TOTALS", "side": "OVER", "line": 6},
                {"selection_id": "home-tt", "market": "TEAM_TOTALS", "team_side": "HOME", "side": "OVER", "line": 3.5},
                {"selection_id": "away-outs", "market": "PITCHER_OUTS", "pitcher_id": "away-p", "side": "OVER", "line": 17.5},
                {"selection_id": "home-outs", "market": "PITCHER_OUTS", "pitcher_id": "home-p", "side": "OVER", "line": 17.5},
            ],
        )

    def test_game_script_and_over_six_are_the_same_event(self):
        out = self._run()
        script = out["game_script"]
        self.assertAlmostEqual(
            script["runs_le_5_p"] + script["runs_eq_6_p"] + script["runs_ge_7_p"],
            1.0,
            places=12,
        )
        over = next(row for row in out["results"] if row["selection_id"] == "over-6")
        self.assertAlmostEqual(over["research_p"], script["runs_ge_7_p"], places=12)
        self.assertAlmostEqual(over["push_p"], script["runs_eq_6_p"], places=12)
        self.assertTrue(out["consistency"]["over_6_equals_runs_ge_7"])

    def test_all_card_rows_share_one_simulation_id_and_score_distribution(self):
        out = self._run()
        self.assertTrue(out["consistency"]["all_results_same_simulation_id"])
        self.assertTrue(out["consistency"]["all_results_same_score_distribution"])
        self.assertEqual({row["simulation_id"] for row in out["results"]}, {out["simulation_id"]})
        self.assertEqual(
            {row["score_distribution_sha256"] for row in out["results"]},
            {out["score_distribution_sha256"]},
        )

    def test_projected_total_is_the_same_path_sample_mean(self):
        out = self._run()
        script = out["game_script"]
        self.assertAlmostEqual(
            script["total_mean_runs"],
            script["away_mean_runs"] + script["home_mean_runs"],
            places=12,
        )

    def test_player_specific_pitcher_histories_do_not_share_a_generic_probability(self):
        out = self._run()
        probs = {row["selection_id"]: row["research_p"] for row in out["results"]}
        self.assertGreater(probs["away-outs"], 0.35)
        self.assertEqual(probs["home-outs"], 0.0)
        self.assertNotEqual(probs["away-outs"], probs["home-outs"])

    def test_score_paths_match_existing_v7_distribution_for_same_identity(self):
        out = self._run()
        identity = {
            "engine": V7_DISTRIBUTION_VERSION,
            "game_id": "test-game",
            "away_mean_runs": 2.9,
            "home_mean_runs": 4.2,
            "feature_source_hash": "feature-hash",
        }
        expected = simulate_game_distribution(
            away_mean_runs=2.9,
            home_mean_runs=4.2,
            total_line=6,
            simulations=4000,
            build_hash=canonical_json_sha256(identity),
        )
        self.assertEqual(out["score_distribution_sha256"], canonical_json_sha256({
            "version": V7_DISTRIBUTION_VERSION,
            "simulations": 4000,
            "seed_policy": expected.seed_policy,
            "joint_score_pmf": expected.joint_score_pmf,
        }))
        over = next(row for row in out["results"] if row["selection_id"] == "over-6")
        self.assertEqual(over["research_p"], expected.over_probability)
        self.assertEqual(over["push_p"], expected.push_probability)


if __name__ == "__main__":
    unittest.main()
