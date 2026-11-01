import unittest

from sportsedge.nfl_team_total_card import build_card, classify

CAP = "2026-11-01T10:57:06-06:00"
PRICED = "2026-11-01T10:58:00-06:00"
KO = "2026-11-01T12:00:00-06:00"


def rec(team, pick, ev_over, ev_under, mu, lane_a, line=24.5, price=-110,
        captured=CAP, kickoff=KO, priced=PRICED):
    return {"row_id": f"G:{team}", "team": team, "pick": pick, "mu": mu,
            "schema": "NFL_TEAM_TOTAL_FORWARD_ROW_V1",
            "engine_id": "NFL_TEAM_TOTAL_DIST_V1", "label": "PROSPECTIVE",
            "kickoff": kickoff, "priced_at": priced, "lane_a": {"team_mean": lane_a},
            "entry": {"line": line, "over_price": price, "under_price": price,
                      "over_captured_at": captured, "under_captured_at": captured},
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
        self.assertEqual(r["status"], "PLAY", r["reasons"])

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
            # ChatGPT review 5730372623: huge ints raised OverflowError
            dict(ev_over=10 ** 1000), dict(mu=10 ** 1000), dict(price=-(10 ** 1000)),
            dict(line=10 ** 1000), dict(lane_a=10 ** 1000),
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

    # ChatGPT review 5729970600 probes
    def test_ev_below_floor_is_pass(self):
        r = classify(rec("X", "PICKED_OVER", 0.01, 0.0, 20, 20))
        self.assertEqual(r["status"], "PASS")
        self.assertIn("EV_BELOW_FLOOR", r["reasons"])
        self.assertEqual(classify(rec("X", "PICKED_OVER", 0.03, 0.0, 20, 20))["status"], "PLAY")

    def test_price_beyond_cap_is_pass(self):
        r = classify(rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20, price=-500))
        self.assertEqual(r["status"], "PASS")
        self.assertIn("PRICE_BEYOND_CAP", r["reasons"])
        self.assertEqual(classify(rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20, price=-165))["status"], "PLAY")

    def test_missing_or_bad_capture_time_is_pass(self):
        for cap, ko, code in ((None, KO, "CAPTURED_AT_MISSING"),
                              ("garbage", KO, "CAPTURED_AT_MISSING"),
                              ("2026-11-01T10:57:06", KO, "CAPTURED_AT_MISSING"),
                              (CAP, None, "KICKOFF_MISSING"),
                              ("2026-11-01T12:05:00-06:00", KO, "CAPTURED_AFTER_KICKOFF")):
            r = classify(rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20, captured=cap, kickoff=ko))
            self.assertEqual(r["status"], "PASS", code)
            self.assertIn(code, r["reasons"])

    def test_malformed_containers_fail_closed(self):
        base = rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20)
        for field, val in (("ev", [0.1]), ("lane_a", [20]), ("entry", [1]),
                           ("ev", "x"), ("lane_a", 5), ("pick", ["PICKED_OVER"])):
            r2 = dict(base)
            r2[field] = val
            r = classify(r2)
            self.assertEqual(r["status"], "PASS", field)
        for bad in (None, [], "x", 3):
            self.assertEqual(classify(bad)["status"], "PASS")

    # ChatGPT review 5730372623: month-old unattributed capture passed
    def test_month_old_capture_is_stale(self):
        r = classify(rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20,
                         captured="2026-10-01T10:57:06-06:00"))
        self.assertEqual(r["status"], "PASS")
        self.assertIn("QUOTE_STALE", r["reasons"])

    def test_quote_age_limit_is_30_minutes(self):
        ok = classify(rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20,
                          captured="2026-11-01T10:28:00-06:00"))
        self.assertEqual(ok["status"], "PLAY", ok["reasons"])
        old = classify(rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20,
                           captured="2026-11-01T10:27:59-06:00"))
        self.assertIn("QUOTE_STALE", old["reasons"])

    def test_priced_time_checks(self):
        for priced, code in ((None, "PRICED_AT_MISSING"),
                             ("2026-11-01T10:58:00", "PRICED_AT_MISSING"),
                             ("2026-11-01T10:50:00-06:00", "PRICED_BEFORE_CAPTURE"),
                             ("2026-11-01T12:01:00-06:00", "PRICED_AFTER_KICKOFF")):
            r = classify(rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20, priced=priced))
            self.assertEqual(r["status"], "PASS", code)
            self.assertIn(code, r["reasons"])

    def test_unattributed_row_is_pass(self):
        for field in ("schema", "engine_id", "label"):
            r2 = rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20)
            del r2[field]
            r = classify(r2)
            self.assertEqual(r["status"], "PASS", field)
            self.assertIn("PROVENANCE_MISSING", r["reasons"])
        r2 = rec("X", "PICKED_OVER", 0.1, 0.0, 20, 20)
        r2["label"] = "RETROSPECTIVE"
        self.assertIn("PROVENANCE_MISSING", classify(r2)["reasons"])


if __name__ == "__main__":
    unittest.main()
