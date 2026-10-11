"""The shared research benchmark must cover all five SportsEdge betting sports.

This verifies policy completeness only; it does not claim a model passed.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/cross_sport_backtest_policy_v1.json"


class CrossSportBacktestPolicyFiveSportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(POLICY.read_text(encoding="utf-8"))

    def test_all_five_sports_explicitly_scoped(self):
        self.assertEqual(set(self.policy["sports"]), {"NFL", "CFB", "MLB", "NBA", "NHL"})

    def test_chronological_evidence_discipline_not_weakened(self):
        policy = self.policy
        self.assertEqual(policy["status"], "RESEARCH_ONLY_FAIL_CLOSED")
        self.assertFalse(policy["production_mutation_allowed"])
        self.assertFalse(policy["fold_discipline"]["test_fold_may_tune_model"])
        self.assertFalse(policy["fold_discipline"]["active_2026_forward_data_may_refit_historical_candidate"])
        self.assertTrue(policy["benchmarking"]["paired_same_event_market_identity_required"])
        for sport, scope in policy["sports"].items():
            with self.subTest(sport=sport):
                self.assertGreaterEqual(scope["minimum_training_seasons"], 3)
                self.assertGreaterEqual(len(scope["preferred_heldout_seasons"]), 3)

    def test_nba_nhl_season_convention_explicit(self):
        for sport in ("NBA", "NHL"):
            note = self.policy["sports"][sport]["notes"]
            self.assertIn("START calendar year", note)

    def test_bet_evidence_requirements_still_include_clv_and_net_roi(self):
        metrics = set(self.policy["required_betting_metrics_when_priced"])
        self.assertTrue({"CLV", "AFTER_VIG_ROI", "PROFIT_UNITS"}.issubset(metrics))


if __name__ == "__main__":
    unittest.main()
