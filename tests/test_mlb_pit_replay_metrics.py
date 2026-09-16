import unittest
from scripts.mlb_pit_replay_metrics import score


class ReplayMetricsTests(unittest.TestCase):
    def row(self, **kw):
        r = {"decision_id":"d1","slate_date_ct":"2026-04-01","market":"MONEYLINE","model_p":"0.60","outcome":"1","decision_no_vig_p":"0.55","close_no_vig_p":"0.57","net_return":"0.8","risked_stake":"1"}
        r.update(kw)
        return r

    def test_scores_core_metrics(self):
        x = score([self.row()])
        self.assertEqual(x["status"], "SCORED_NOT_PROMOTED")
        self.assertAlmostEqual(x["brier"], 0.16)
        self.assertAlmostEqual(x["mean_clv"], 0.02)
        self.assertAlmostEqual(x["roi"], 0.8)

    def test_duplicate_decision_fails(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            score([self.row(), self.row()])

    def test_bad_probability_fails(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            score([self.row(model_p="1.1")])

    def test_empty_is_not_evidence(self):
        self.assertEqual(score([])["status"], "NO_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
