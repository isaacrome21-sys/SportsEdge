import unittest

from sportsedge.core.clv.football import CLVDecision, CLVClose, score_clv, summarize_clv
from sportsedge.core.promotion.football import FootballPromotionEvidence, evaluate_football_promotion
from sportsedge.sports.cfb.m2 import build_cfb_m2_features, walkforward_m2_vs_m1


class FootballRoadmapTenToTwelveTests(unittest.TestCase):
    def test_task_10_clv_scores_probability_delta_and_reports_rejects(self):
        decisions = [
            CLVDecision("2025-09-01T12:00:00Z", "g1", "cfb", "spread", "home", "book", -3.0, -110, 0.56, 0.52, 0.04, 0.02, 0.5, "OFFICIAL"),
            CLVDecision("2025-09-01T12:05:00Z", "g2", "cfb", "spread", "away", "book", 7.0, -105, 0.51, 0.50, 0.01, 0.005, 0.0, "REJECTED_EDGE"),
        ]
        closes = [
            CLVClose("g1", "spread", "home", -3.5, -115, 0.55),
            CLVClose("g2", "spread", "away", 6.5, -110, 0.49),
        ]
        scored = score_clv(decisions, closes)
        self.assertAlmostEqual(scored[0].clv, 0.03)
        self.assertAlmostEqual(scored[1].clv, -0.01)
        report = summarize_clv(scored)
        self.assertIn(("cfb", "spread", "OFFICIAL"), report)
        self.assertIn(("cfb", "spread", "REJECTED"), report)
        self.assertEqual(report[("cfb", "spread", "OFFICIAL")].n, 1)

    def test_task_11_promotion_uses_clv_not_roi_and_can_emit_zero(self):
        evidence = FootballPromotionEvidence(
            math_valid=True,
            fold_wins=12,
            fold_total=19,
            ci_attested=True,
            calibration_max_bin_deviation=0.02,
            calibration_threshold=0.03,
            logged_plays=250,
            mean_clv=0.008,
            clv_t_stat=2.4,
        )
        self.assertEqual(evaluate_football_promotion(evidence), "DEPLOYED")

        nothing = FootballPromotionEvidence(
            math_valid=True,
            fold_wins=5,
            fold_total=10,
            ci_attested=True,
            calibration_max_bin_deviation=0.02,
            calibration_threshold=0.03,
            logged_plays=250,
            mean_clv=-0.001,
            clv_t_stat=-0.2,
        )
        self.assertNotEqual(evaluate_football_promotion(nothing), "DEPLOYED")
        self.assertFalse(hasattr(nothing, "roi"))

    def test_task_12_cfb_m2_is_market_blind_and_walkforward_reports_per_fold_market(self):
        feature_row = build_cfb_m2_features({
            "off_epa": 0.12,
            "def_epa": -0.04,
            "opp_off_epa": 0.03,
            "opp_def_epa": -0.01,
            "returning_production": 0.68,
            "prior_rating": 8.5,
            "venue_hfa": 2.1,
            "feature_asof_ts": "2021-08-30T12:00:00Z",
            "game_start_ts": "2021-09-04T19:00:00Z",
        })
        banned = {"spread_line", "total_line", "price", "implied_probability", "novig_prob"}
        self.assertTrue(banned.isdisjoint(feature_row))

        rows = []
        for season in range(2018, 2023):
            for market in ("spread", "total"):
                for i in range(8):
                    y = (i + season) % 2
                    rows.append({
                        "season": season,
                        "market": market,
                        "outcome": y,
                        "m1_prob": 0.55 if y else 0.45,
                        "m2_prob": 0.60 if y else 0.40,
                    })
        report = walkforward_m2_vs_m1(rows, min_train_seasons=2)
        self.assertTrue(report)
        self.assertTrue(all(r.test_season > max(r.train_seasons) for r in report))
        self.assertEqual({r.market for r in report}, {"spread", "total"})
        self.assertTrue(all(r.m2_log_loss < r.m1_log_loss for r in report))


if __name__ == "__main__":
    unittest.main()
