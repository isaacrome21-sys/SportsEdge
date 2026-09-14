import unittest

from sportsedge.dfs.mlb_pitcher_contract import normalize_starter_path


class MlbPitcherAccountingV3Tests(unittest.TestCase):
    def test_four_strikeouts_with_three_outs_is_valid_when_bf_supports_it(self):
        sample = {
            "outs": 3,
            "strikeouts": 4,
            "earned_runs": 0,
            "hits_allowed": 0,
            "walks_allowed": 0,
            "hbp_allowed": 0,
            "starter_exit_batters_faced": 4,
            "starter_exit_pitch_count": 16,
            "starter_scoped_events": 1,
            "hook_endogenous_to_path": 1,
            "hook_decision_batter_by_batter": 1,
            "hook_conditioned_on_pitch_count": 1,
            "hook_conditioned_on_runs_allowed": 1,
            "bullpen_remainder_routed": 1,
            "bullpen_hits_allowed": 0,
            "opponent_team_hits": 0,
            "game_simulated_to_final": 1,
            "lead_at_exit": 0,
            "lead_preserved_to_final": 0,
        }

        normalized = normalize_starter_path(sample)

        self.assertEqual(normalized["outs"], 3.0)
        self.assertEqual(normalized["strikeouts"], 4.0)
        self.assertEqual(normalized["win_probability"], 0.0)


if __name__ == "__main__":
    unittest.main()
