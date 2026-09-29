import unittest

from sportsedge.mlb_joint_card_coupled_research import simulate_score_compatible_joint_card
from sportsedge.mlb_joint_card_research import MLBJointCardResearchError
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import V7_DISTRIBUTION_VERSION, simulate_game_distribution


class TestMLBJointCardCoupledResearch(unittest.TestCase):
    def _pools(self):
        return {
            "away-p": [
                {"strikeouts": 8, "outs": 18, "earned_runs": 0, "hits_allowed": 4, "walks_allowed": 1},
                {"strikeouts": 7, "outs": 17, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2},
                {"strikeouts": 9, "outs": 19, "earned_runs": 1, "hits_allowed": 3, "walks_allowed": 1},
                {"strikeouts": 6, "outs": 16, "earned_runs": 3, "hits_allowed": 6, "walks_allowed": 2},
                {"strikeouts": 10, "outs": 20, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 0},
            ],
            # Deliberately no zero-ER row: zero-run opponent paths must use the
            # explicit capped-support fallback rather than emit an impossible ER.
            "home-p": [
                {"strikeouts": 5, "outs": 14, "earned_runs": 4, "hits_allowed": 7, "walks_allowed": 3},
                {"strikeouts": 4, "outs": 15, "earned_runs": 3, "hits_allowed": 6, "walks_allowed": 2},
                {"strikeouts": 6, "outs": 16, "earned_runs": 4, "hits_allowed": 8, "walks_allowed": 2},
                {"strikeouts": 3, "outs": 13, "earned_runs": 5, "hits_allowed": 9, "walks_allowed": 4},
                {"strikeouts": 5, "outs": 15, "earned_runs": 3, "hits_allowed": 7, "walks_allowed": 3},
            ],
        }

    def _run(self):
        return simulate_score_compatible_joint_card(
            game_id="test-game",
            away_mean_runs=2.9,
            home_mean_runs=4.2,
            feature_source_hash="feature-hash",
            simulations=5000,
            pitcher_pools=self._pools(),
            pitcher_team_sides={"away-p": "AWAY", "home-p": "HOME"},
            selections=[
                {"selection_id": "home-ml", "market": "MONEYLINE", "side": "HOME", "line": 0},
                {"selection_id": "over-6", "market": "TOTALS", "side": "OVER", "line": 6},
                {"selection_id": "home-score", "market": "TEAM_TOTALS", "team_side": "HOME", "side": "OVER", "line": 0.5},
                {"selection_id": "away-score", "market": "TEAM_TOTALS", "team_side": "AWAY", "side": "OVER", "line": 0.5},
                {"selection_id": "away-p-er", "market": "PITCHER_ER", "pitcher_id": "away-p", "side": "OVER", "line": 0.5},
                {"selection_id": "home-p-er", "market": "PITCHER_ER", "pitcher_id": "home-p", "side": "OVER", "line": 0.5},
                {"selection_id": "away-p-outs", "market": "PITCHER_OUTS", "pitcher_id": "away-p", "side": "OVER", "line": 17.5},
                {"selection_id": "home-p-outs", "market": "PITCHER_OUTS", "pitcher_id": "home-p", "side": "OVER", "line": 17.5},
            ],
        )

    def test_pitcher_er_is_pathwise_compatible_with_opponent_score(self):
        out = self._run()
        self.assertTrue(out["consistency"]["pitcher_er_never_exceeds_opponent_runs"])
        for row in out["pitcher_score_compatibility"].values():
            self.assertEqual(row["earned_runs_excess_paths"], 0)
            self.assertEqual(
                row["direct_paths"] + row["resampled_feasible_paths"] + row["capped_support_fallback_paths"],
                out["mc_paths"],
            )
        self.assertGreater(
            out["pitcher_score_compatibility"]["home-p"]["capped_support_fallback_paths"],
            0,
        )

    def test_pitcher_er_over_half_is_subset_of_opponent_scoring(self):
        out = self._run()
        p = {row["selection_id"]: row["research_p"] for row in out["results"]}
        # Away pitcher faces HOME offense; home pitcher faces AWAY offense.
        self.assertLessEqual(p["away-p-er"], p["home-score"])
        self.assertLessEqual(p["home-p-er"], p["away-score"])

    def test_game_score_distribution_is_bit_for_bit_existing_v7(self):
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
            simulations=5000,
            build_hash=canonical_json_sha256(identity),
        )
        expected_sha = canonical_json_sha256({
            "version": V7_DISTRIBUTION_VERSION,
            "simulations": 5000,
            "seed_policy": expected.seed_policy,
            "joint_score_pmf": expected.joint_score_pmf,
        })
        self.assertEqual(out["score_distribution_sha256"], expected_sha)
        over = next(row for row in out["results"] if row["selection_id"] == "over-6")
        self.assertEqual(over["research_p"], expected.over_probability)
        self.assertEqual(over["push_p"], expected.push_probability)

    def test_repeated_run_is_deterministic(self):
        self.assertEqual(self._run(), self._run())

    def test_pitcher_side_binding_is_required(self):
        with self.assertRaises(MLBJointCardResearchError):
            simulate_score_compatible_joint_card(
                game_id="test-game",
                away_mean_runs=3.0,
                home_mean_runs=4.0,
                feature_source_hash="x",
                simulations=1000,
                pitcher_pools={"away-p": self._pools()["away-p"]},
                pitcher_team_sides={},
                selections=[
                    {"selection_id": "p", "market": "PITCHER_ER", "pitcher_id": "away-p", "side": "OVER", "line": 1.5}
                ],
            )


if __name__ == "__main__":
    unittest.main()
