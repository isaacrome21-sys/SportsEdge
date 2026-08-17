import unittest

from sportsedge.sports.nfl.m2 import build_nfl_m2_features, walkforward_nfl_m2_vs_m1
from sportsedge.core.prior_decay import fit_weekly_prior_decay
from sportsedge.core.live_odds.football import football_live_odds_ready
from sportsedge.sports.cfb.promotion_attempt import run_cfb_promotion_attempt
from sportsedge.core.promotion.football import FootballPromotionEvidence


class FootballRoadmapThirteenToSixteenTests(unittest.TestCase):
    def test_task_13_nfl_m2_has_explicit_qb_identity_and_is_market_blind(self):
        features = build_nfl_m2_features({
            "off_epa": 0.10, "def_epa": -0.03,
            "pass_epa": 0.16, "rush_epa": 0.02,
            "opp_off_epa": 0.04, "opp_def_epa": -0.01,
            "pressure_for": 0.31, "pressure_allowed": 0.27,
            "success_rate": 0.48, "explosive_rate": 0.12,
            "rest_diff_days": 1, "travel_miles": 740, "timezone_crossings": 1,
            "short_week": 0, "bye_week": 0, "wind_mph": 11, "roof_closed": 0,
            "qb_id": "00-0033873", "qb_adjustment": 2.4,
            "prior_efficiency": 0.08, "prior_weight": 0.65,
            "feature_asof_ts": "2025-09-01T12:00:00Z",
            "game_start_ts": "2025-09-07T17:00:00Z",
        })
        self.assertEqual(features["qb_id"], "00-0033873")
        self.assertAlmostEqual(features["qb_adjustment"], 2.4)
        for bad in ("spread_line", "total_line", "price", "implied_probability", "novig_prob"):
            self.assertNotIn(bad, features)
        with self.assertRaisesRegex(ValueError, "M2_MARKET_DATA_PROHIBITED"):
            build_nfl_m2_features({
                "off_epa": 0.1, "def_epa": -0.03, "pass_epa": 0.16, "rush_epa": 0.02,
                "opp_off_epa": 0.04, "opp_def_epa": -0.01, "pressure_for": 0.31,
                "pressure_allowed": 0.27, "success_rate": 0.48, "explosive_rate": 0.12,
                "rest_diff_days": 1, "travel_miles": 740, "timezone_crossings": 1,
                "short_week": 0, "bye_week": 0, "wind_mph": 11, "roof_closed": 0,
                "qb_id": "q", "qb_adjustment": 2.4, "prior_efficiency": 0.08,
                "prior_weight": 0.65, "feature_asof_ts": "2025-09-01T12:00:00Z",
                "game_start_ts": "2025-09-07T17:00:00Z", "spread_line": -3.0,
            })

    def test_task_13_walkforward_reports_per_fold_market(self):
        rows = []
        for season in range(2019, 2025):
            for market in ("spread", "total"):
                for i in range(6):
                    y = (i + season) % 2
                    rows.append({"season": season, "market": market, "outcome": y,
                                 "m1_prob": 0.55 if y else 0.45,
                                 "m2_prob": 0.60 if y else 0.40})
        report = walkforward_nfl_m2_vs_m1(rows, min_train_seasons=2)
        self.assertTrue(report)
        self.assertEqual({r.market for r in report}, {"spread", "total"})
        self.assertTrue(all(r.test_season > max(r.train_seasons) for r in report))

    def test_task_14_prior_decay_is_fit_not_assumed(self):
        rows = []
        for week in range(1, 7):
            for i in range(20):
                truth = (i % 2) * 2 - 1
                prior_pred = truth * (1.0 - 0.12 * (week - 1))
                current_pred = truth * (0.18 * week)
                rows.append({"week": week, "target": truth, "prior_pred": prior_pred, "current_pred": current_pred})
        curve = fit_weekly_prior_decay(rows, weeks=range(1, 7), grid_step=0.05)
        self.assertEqual(tuple(curve), (1, 2, 3, 4, 5, 6))
        self.assertTrue(all(0.0 <= curve[w] <= 1.0 for w in curve))
        self.assertGreaterEqual(curve[1], curve[6])
        self.assertNotEqual([curve[w] for w in curve], [1.0, .8, .6, .4, .2, 0.0])

    def test_task_15_live_odds_readiness_fails_closed_without_key_and_unblocks_with_key(self):
        self.assertFalse(football_live_odds_ready({}).ready)
        ready = football_live_odds_ready({"ODDS_API_KEY": "secret-placeholder"})
        self.assertTrue(ready.ready)
        self.assertNotIn("secret-placeholder", repr(ready))

    def test_task_16_cfb_promotion_attempt_can_correctly_emit_zero_official_plays(self):
        evidence = FootballPromotionEvidence(
            math_valid=True, fold_wins=8, fold_total=11, ci_attested=True,
            calibration_max_bin_deviation=0.02, calibration_threshold=0.03,
            logged_plays=40, mean_clv=0.004, clv_t_stat=1.1,
        )
        attempt = run_cfb_promotion_attempt(
            market="spread", evidence=evidence,
            candidates=[{"game_id": "g1", "qualifies": True}],
            as_of_date="2026-08-29",
        )
        self.assertEqual(attempt.stage, "CI_ATTESTED")
        self.assertEqual(attempt.official_plays, ())
        self.assertTrue(attempt.zero_is_valid)


if __name__ == "__main__":
    unittest.main()
