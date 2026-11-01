import unittest

from sportsedge.nfl_team_total_card import build_card, classify


def rec(team, pick, ev_over, ev_under, mu, lane_a, line=24.5):
    return {"row_id": f"G:{team}", "team": team, "pick": pick, "mu": mu,
            "lane_a": {"team_mean": lane_a},
            "entry": {"line": line, "over_price": -110, "under_price": -110},
            "ev": {"OVER": ev_over, "UNDER": ev_under}}


class CardTests(unittest.TestCase):
    def test_negative_ev_pick_is_pass(self):  # JAX 2026-11-01
        r = classify(rec("JAX", "PICKED_OVER", -0.108, -0.009, 29.58, 22.47))
        self.assertEqual(r["status"], "PASS")
        self.assertIn("NEGATIVE_EV_ON_PICKED_SIDE", r["reasons"])

    def test_lane_a_divergence_is_pass(self):  # DET 2026-11-01
        r = classify(rec("DET", "PICKED_UNDER", -0.77, 0.61, 15.80, 22.28))
        self.assertEqual(r["status"], "PASS")
        self.assertIn("LANE_A_DIVERGENCE", r["reasons"])
        self.assertIn("EV_IMPLAUSIBLE", r["reasons"])

    def test_clean_pick_is_play(self):  # NYJ 2026-11-01
        r = classify(rec("NYJ", "PICKED_UNDER", -0.33, 0.213, 21.37, 21.15))
        self.assertEqual(r["status"], "PLAY")

    def test_passed_rows_excluded_and_ranked_by_ev(self):
        card = build_card([
            rec("CIN", "PICKED_UNDER", -0.31, 0.207, 27.42, 22.84),
            rec("NYJ", "PICKED_UNDER", -0.33, 0.213, 21.37, 21.15),
            rec("PIT", "PASSED", 0.0, 0.0, 20.0, 20.0),
        ])
        self.assertEqual([r["team"] for r in card], ["NYJ", "CIN"])


if __name__ == "__main__":
    unittest.main()
