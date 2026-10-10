"""CFB price math must treat whole-number game contracts as pushable."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "cfb_sdv_card_push",
    Path(__file__).resolve().parents[1] / "scripts" / "run_cfb_sdv_card_v2.py",
)
card = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card)


class PushAwareCFBTest(unittest.TestCase):
    def test_integer_total_has_nonzero_push_and_conditional_half(self):
        win, lose, push = card.model_distribution("TOTAL", "OVER", 50.0, 26, 24)
        self.assertGreater(push, 0.02)
        self.assertAlmostEqual(win + lose + push, 1.0)
        self.assertAlmostEqual(win, lose, places=7)
        self.assertAlmostEqual(card.model_prob("TOTAL", "OVER", 50.0, 26, 24), .5)

    def test_integer_spread_sides_mirror_with_push(self):
        h = card.model_distribution("SPREAD", "HOME", -3.0, 27, 23)
        a = card.model_distribution("SPREAD", "AWAY", 3.0, 27, 23)
        self.assertAlmostEqual(h[0], a[1])
        self.assertAlmostEqual(h[1], a[0])
        self.assertAlmostEqual(h[2], a[2])
        self.assertGreater(h[2], 0)

    def test_half_point_never_pushes(self):
        for market, side, line in (
            ("SPREAD", "HOME", -3.5),
            ("SPREAD", "AWAY", 3.5),
            ("TOTAL", "OVER", 50.5),
            ("TOTAL", "UNDER", 50.5),
        ):
            w, l, p = card.model_distribution(market, side, line, 27, 23)
            self.assertEqual(p, 0)
            self.assertAlmostEqual(w + l, 1.0)
        self.assertAlmostEqual(card.model_prob("TOTAL", "OVER", 50.5, 26, 24),
                               card.phi((50.0 - 50.5) / card.COMBINED_SIGMA))

    def test_expected_roi_uses_actual_win_loss_not_push_as_loss(self):
        rows = card.price_game("g", 26.0, 24.0, [
            {"market": "TOTAL", "side": "OVER", "line": 50.0, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 50.0, "american_odds": -110},
        ])
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertGreater(row["model_push_p"], 0.0)
            self.assertAlmostEqual(
                row["expected_roi"],
                round(row["model_win_p"] * (100 / 110) - row["model_loss_p"], 4),
                delta=0.0002
            )
            self.assertAlmostEqual(row["model_p"], .5, places=4)
            self.assertEqual(row["model_prob_basis"], "CONDITIONAL_WIN_GIVEN_NO_PUSH")
            self.assertNotEqual(row["bet_status"], "BET")

    def test_symmetry_of_over_under_integer(self):
        rows = card.price_game("g", 30, 25, [
            {"market": "TOTAL", "side": "OVER", "line": 54, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 54, "american_odds": -110},
        ])
        self.assertAlmostEqual(sum(row["model_p"] for row in rows), 1.0, places=6)
        self.assertAlmostEqual(rows[0]["model_push_p"], rows[1]["model_push_p"])
        self.assertAlmostEqual(rows[0]["model_win_p"], rows[1]["model_loss_p"], places=6)

    def test_moneyline_still_no_push_and_real_payout(self):
        rows = card.price_game("g", 28, 24, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": -120},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": 105},
        ])
        self.assertTrue(all(r["model_push_p"] == 0 for r in rows))
        for row in rows:
            odds = row["american_odds"]
            profit = odds / 100 if odds > 0 else 100 / abs(odds)
            self.assertAlmostEqual(row["expected_roi"],
                                   round(row["model_p"] * (1 + profit) - 1, 4))

    def test_rejects_nonhalfpint_lines(self):
        with self.assertRaisesRegex(ValueError, "LINE_MUST_BE_WHOLE_OR_HALF"):
            card.model_distribution("TOTAL", "OVER", 50.25, 26, 24)

    def test_unvalidated_markets_stay_unqualified(self):
        self.assertEqual(card.VALIDATED_MARKETS, frozenset())
        rows = card.price_game("g", 32, 26, [
            {"market": "TOTAL", "side": "OVER", "line": 55.0, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 55.0, "american_odds": -110},
        ])
        self.assertTrue(all(r["bet_status"] != "BET" for r in rows))


if __name__ == "__main__":
    unittest.main()
