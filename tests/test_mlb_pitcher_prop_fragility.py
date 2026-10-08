import unittest
from scripts.audit_mlb_pitcher_prop_fragility import audit, break_even, wilson_interval


class PitcherFragilityAuditTest(unittest.TestCase):
    def test_break_even(self):
        self.assertAlmostEqual(break_even(159), 100 / 259)
        self.assertAlmostEqual(break_even(-117), 117 / 217)

    def test_wilson_not_100k_paths(self):
        lo, hi = wilson_interval(0.89, 10)
        self.assertLess(lo, 0.65)
        self.assertGreater(hi, 0.89)

    def test_research_only_and_low_support(self):
        row = {
            "engine_market": "PITCHER_OUTS",
            "pitcher_name": "Test Pitcher", "side": "OVER", "line": 12.5,
            "american_odds": 159, "research_p": 0.89,
            "ev_per_dollar": 1.30,
            "probability_source": "CANONICAL_PITCHER_MARGINAL",
            "probability_meta": {"effective_history_starts": 10},
            "postseason_workload_adjusted": False,
        }
        out = audit({"results": [row]})
        self.assertFalse(out["pitcher_props_card_eligible"])
        self.assertFalse(out["rows"][0]["card_eligible"])
        self.assertIn("EXTREME_RESEARCH_EV", out["rows"][0]["flags"])
        self.assertIn("POSTSEASON_WORKLOAD_NOT_ADJUSTED", out["rows"][0]["flags"])

    def test_fail_closed_on_score_conditioned_pitcher(self):
        row = {"engine_market": "PITCHER_K", "probability_source": "SCORE_COMPATIBLE_GAME_PATHS"}
        with self.assertRaises(ValueError):
            audit({"results": [row]})


if __name__ == "__main__":
    unittest.main()
