import unittest

from scripts.mlb_pit_replay_metrics import cr1_mean, cr1_ratio, score


class ReplayMetricsTests(unittest.TestCase):
    def row(self, **kw):
        r = {
            "decision_id": "d1",
            "slate_date_ct": "2026-04-01",
            "market": "MONEYLINE",
            "model_p": "0.60",
            "outcome": "1",
            "decision_no_vig_p": "0.55",
            "close_no_vig_p": "0.57",
            "net_return": "0.8",
            "risked_stake": "1",
        }
        r.update(kw)
        return r

    def test_scores_core_metrics_without_iid_fallback(self):
        x = score([self.row()])
        self.assertEqual(x["status"], "SCORED_NOT_PROMOTED")
        self.assertAlmostEqual(x["brier"], 0.16)
        self.assertAlmostEqual(x["clv"]["estimate"], 0.02)
        self.assertAlmostEqual(x["roi"]["estimate"], 0.8)
        self.assertEqual(x["clv"]["status"], "INSUFFICIENT_CLUSTERS_NO_IID_FALLBACK")
        self.assertEqual(x["roi"]["status"], "INSUFFICIENT_CLUSTERS_NO_IID_FALLBACK")
        self.assertIsNone(x["clv"]["t_cr1"])

    def test_cr1_mean_clusters_by_slate_not_rows(self):
        result = cr1_mean([0.02, 0.04, -0.01], ["2026-04-01", "2026-04-01", "2026-04-02"])
        self.assertEqual(result["clusters"], 2)
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["status"], "CR1_SCORED")
        self.assertIsNotNone(result["se_cr1"])
        self.assertIsNotNone(result["t_cr1"])

    def test_roi_cr1_uses_ratio_definition(self):
        result = cr1_ratio([1.0, -0.5], [2.0, 1.0], ["2026-04-01", "2026-04-02"])
        self.assertAlmostEqual(result["estimate"], 0.5 / 3.0)
        self.assertEqual(result["clusters"], 2)
        self.assertEqual(result["status"], "CR1_SCORED")

    def test_missing_outcome_is_excluded_from_binary_scoring(self):
        rows = [
            self.row(decision_id="d1", outcome=""),
            self.row(decision_id="d2", slate_date_ct="2026-04-02", outcome="0"),
        ]
        x = score(rows)
        self.assertEqual(x["binary_score_n"], 1)
        self.assertEqual(x["excluded_from_binary_scoring_missing_outcome"], 1)
        self.assertAlmostEqual(x["brier"], 0.36)

    def test_missing_close_is_excluded_not_imputed(self):
        rows = [
            self.row(decision_id="d1", close_no_vig_p=""),
            self.row(decision_id="d2", slate_date_ct="2026-04-02", close_no_vig_p="0.58"),
        ]
        x = score(rows)
        self.assertEqual(x["excluded_from_clv_missing_close"], 1)
        self.assertEqual(x["clv"]["n"], 1)
        self.assertAlmostEqual(x["clv"]["estimate"], 0.03)

    def test_missing_settlement_is_excluded_not_zeroed(self):
        rows = [
            self.row(decision_id="d1", net_return="", risked_stake=""),
            self.row(decision_id="d2", slate_date_ct="2026-04-02", net_return="1.0", risked_stake="2.0"),
        ]
        x = score(rows)
        self.assertEqual(x["excluded_from_roi_missing_settlement"], 1)
        self.assertEqual(x["roi"]["n"], 1)
        self.assertAlmostEqual(x["roi"]["estimate"], 0.5)

    def test_duplicate_decision_fails(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            score([self.row(), self.row()])

    def test_bad_probability_fails(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            score([self.row(model_p="1.1")])

    def test_bad_binary_outcome_fails(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            score([self.row(outcome="0.5")])

    def test_empty_is_not_evidence(self):
        self.assertEqual(score([])["status"], "NO_EVIDENCE")

    def test_nway_market_is_explicitly_unauthorized(self):
        x = score([self.row(market="FIRST_HOME_RUN")], unauthorized=True)
        self.assertEqual(x["status"], "N_WAY_UNAUTHORIZED_V1")
        self.assertIsNone(x["clv"]["estimate"])


if __name__ == "__main__":
    unittest.main()
