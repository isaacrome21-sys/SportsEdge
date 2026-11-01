import unittest

from sportsedge.nfl_team_total_card import build_card, classify


def rec(team, pick, ev_over, ev_under, mu, lane_a, line=24.5, price=-110):
    return {"row_id": f"G:{team}", "team": team, "pick": pick, "mu": mu,
            "lane_a": {"team_mean": lane_a},
            "entry": {"line": line, "over_price": price, "under_price": price},
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

    def test_nan_ev_is_pass(self):  # ChatGPT repro, review 5729925699
        r = classify(rec("X", "PICKED_OVER", float("nan"), 0.0, 20, 20, line=20.5))
        self.assertEqual(r["status"], "PASS")
        self.assertIn("BAD_INPUT_EV", r["reasons"])

    def test_nonfinite_or_bool_inputs_are_pass(self):
        bad = [
            dict(ev_over=float("inf")), dict(ev_over=True), dict(ev_over="x"),
            dict(mu=float("nan")), dict(mu=None), dict(lane_a=float("nan")),
            dict(line=float("nan")), dict(price=float("nan")), dict(price=True),
            dict(price=50),
        ]
        for kw in bad:
            args = dict(team="X", pick="PICKED_OVER", ev_over=0.1, ev_under=0.0, mu=20, lane_a=20)
            args.update(kw)
            r = classify(rec(**args))
            self.assertEqual(r["status"], "PASS", kw)
            self.assertTrue(r["reasons"], kw)

    def test_missing_entry_is_pass_not_crash(self):
        r = classify({"pick": "PICKED_OVER", "ev": {"OVER": 0.1}, "mu": 20, "lane_a": {"team_mean": 20}})
        self.assertEqual(r["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
