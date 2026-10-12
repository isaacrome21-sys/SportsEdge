"""MLB team total research lane: verified run means, honest push and price gates."""
import math
import unittest
from datetime import datetime, timezone

from artifacts import free_models
from artifacts.run_it_full import run_full
from tests.test_prepricing_ingestion import FakeGetter, mlb_mapping, mlb_row, NOW, KICKOFF_MLB


class MLBTeamTotalsResearchTests(unittest.TestCase):
    def ticket(self, *, side="OVER", team="HOME", line=3.5, odds=-110,
               quote=None, **overrides):
        row = mlb_row()
        row.update({
            "market": "TEAM_TOTALS", "side": side, "team": team,
            "line": line, "odds": odds,
            "quote_captured_at": quote or NOW.isoformat(),
        })
        row.update(overrides)
        return row

    def test_poisson_total_probability_matches_team_only_run_mean(self):
        h, a = 3.346, 3.309
        over, push = free_models.model_probability(
            "MLB", "TEAM_TOTAL", "OVER", 3.5, h, a, team_side="HOME")
        under, under_push = free_models.model_probability(
            "MLB", "TEAM_TOTAL", "UNDER", 3.5, h, a, team_side="HOME")
        expected = 1 - sum(math.exp(-h) * h ** k / math.factorial(k) for k in range(4))
        self.assertAlmostEqual(over, expected, places=8)
        self.assertAlmostEqual(over + under, 1.0, places=8)
        self.assertAlmostEqual(push, 0.0)
        self.assertAlmostEqual(under_push, 0.0)
        away, _ = free_models.model_probability(
            "MLB", "TEAM_TOTAL", "OVER", 3.5, h, a, team_side="AWAY")
        self.assertNotEqual(over, away)

    def test_integer_team_total_push_and_refund(self):
        over, push = free_models.model_probability(
            "MLB", "TEAM_TOTAL", "OVER", 3.0, 3.346, 3.309, team_side="HOME")
        under, under_push = free_models.model_probability(
            "MLB", "TEAM_TOTAL", "UNDER", 3.0, 3.346, 3.309, team_side="HOME")
        expected_push = math.exp(-3.346) * 3.346 ** 3 / 6
        self.assertAlmostEqual(push, expected_push, places=8)
        self.assertAlmostEqual(under_push, push, places=8)
        self.assertAlmostEqual(over + under + push, 1.0, places=8)

    def test_full_runner_prices_both_teams_and_attests_independent_context(self):
        rows = [self.ticket(team="HOME", side="OVER", line=3.5, odds=-110),
                self.ticket(team="AWAY", side="UNDER", line=3.5, odds=+100)]
        card = run_full({"lines": rows}, now=NOW, getter=FakeGetter(mlb_mapping()))
        actual = card["evaluated_rows"]
        self.assertEqual(len(actual), 2)
        self.assertTrue(all(x["market"] == "TEAM_TOTAL" for x in actual))
        self.assertTrue(all(x["pricing_lane"] == free_models.LANE_A for x in actual))
        self.assertTrue(all(x["pricing_lanes"]["lane_b_anchored"]["status"]
                            == "LANE_B_UNAVAILABLE" for x in actual))
        self.assertEqual(actual[0]["team_side"], "HOME")
        self.assertEqual(actual[1]["team_side"], "AWAY")
        self.assertIn("Milwaukee Brewers OVER", actual[0]["selection"])
        self.assertIn("Los Angeles Dodgers UNDER", actual[1]["selection"])
        self.assertTrue(all(x["validated_profitability"] is False for x in actual))
        self.assertTrue(all(x["prepricing_adjustments"]["verification_status"] == "VERIFIED"
                            for x in actual))
        self.assertTrue(all(0 < x["estimate_p"] < 1 for x in actual))
        self.assertAlmostEqual(actual[0]["estimate_p"] + actual[0]["push_p"] +
                               actual[0]["loss_p"], 1.0, places=5)

    def test_home_and_away_quote_pairs_never_cross_bind(self):
        rows = [
            self.ticket(team="HOME", side="OVER", line=3.5, odds=-125),
            self.ticket(team="HOME", side="UNDER", line=3.5, odds=+105),
            self.ticket(team="AWAY", side="OVER", line=3.5, odds=+130),
            self.ticket(team="AWAY", side="UNDER", line=3.5, odds=-150),
        ]
        card = run_full({"lines": rows}, now=NOW, getter=FakeGetter(mlb_mapping()))
        priced = card["evaluated_rows"]
        self.assertEqual(len(priced), 4)
        self.assertEqual([x["team_side"] for x in priced],
                         ["HOME", "HOME", "AWAY", "AWAY"])
        home = priced[0]["independent_projection"]
        away = priced[2]["independent_projection"]
        self.assertNotEqual(home.get("paired_market_no_vig_p"),
                            away.get("paired_market_no_vig_p"))

    def test_bad_team_ambiguous_total_and_stale_quote_fail_closed(self):
        getter = FakeGetter(mlb_mapping())
        for value in ("Chicago Cubs", "", "MIL"):
            with self.subTest(team=value):
                card = run_full({"lines": [self.ticket(team=value)]},
                                now=NOW, getter=getter)
                self.assertIn("INVALID", card["evaluated_rows"][0]["status"])
        for line in (-1, 0.25, 3.25):
            with self.subTest(line=line):
                card = run_full({"lines": [self.ticket(line=line)]},
                                now=NOW, getter=getter)
                self.assertIn("INVALID", card["evaluated_rows"][0]["status"])
        old = "2026-10-11T17:50:00Z"
        stale = run_full({"lines": [self.ticket(quote=old)]},
                         now=NOW, getter=getter)["evaluated_rows"][0]
        self.assertEqual(stale["status"], "WATCH_QUOTE_NOT_CURRENT")
        self.assertEqual(stale["model_validation"], "NOT_PROVEN_VS_CLOSE")

    def test_no_public_fixture_cannot_price(self):
        row = self.ticket()
        card = run_full({"lines": [row]}, now=NOW, getter=lambda url: {})
        self.assertEqual(card["evaluated_rows"][0]["status"],
                         "BLOCKED_PREPRICING_FIXTURE_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
