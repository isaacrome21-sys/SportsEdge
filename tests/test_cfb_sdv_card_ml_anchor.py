"""Moneyline must use the same market-anchored margin as the spread."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cfb_card_v2_ml_anchor", ROOT / "scripts" / "run_cfb_sdv_card_v2.py")
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)

FIT = {"intercept": 0.0, "weight": 0.2, "n": 100}
# Indiana @ Nebraska, DK 2026-10-10 04:54 CT: model says Nebraska by ~2, market Indiana by 8.5.
QUOTES = card.expand_compact({"away": "Indiana", "home": "Nebraska", "ml": [-340, 270],
                              "spread": [-8.5, -108, -112]})["quotes"]


class MoneylineAnchorTest(unittest.TestCase):
    def priced(self, home, away):
        ctx = card.anchored_spread_context(home, away, QUOTES, fit=FIT)
        rows = card.price_game("g", home, away, QUOTES, spread_context=ctx)
        return ctx, {(r["market"], r["side"]): r for r in rows}

    def test_moneyline_uses_anchored_margin(self):
        ctx, rows = self.priced(28.2, 26.0)
        ml_home = rows[("MONEYLINE", "HOME")]
        expected = card.phi(ctx["adjusted_home_margin"] / card.COMBINED_SIGMA)
        self.assertAlmostEqual(ml_home["model_p"], round(expected, 4), places=4)
        self.assertIn("adjusted_home_margin", ml_home)

    def test_moneyline_and_spread_agree_in_direction(self):
        _ctx, rows = self.priced(28.2, 26.0)
        ml_edge = rows[("MONEYLINE", "HOME")]["edge"]
        spread_edge = rows[("SPREAD", "HOME")]["edge"]
        self.assertEqual(ml_edge > 0, spread_edge > 0)
        raw = {r["side"]: r for r in card.price_game("g", 28.2, 26.0, QUOTES) if r["market"] == "MONEYLINE"}
        self.assertLess(ml_edge, raw["HOME"]["edge"])

    def test_moneyline_lean_respects_anchor_forward_threshold(self):
        _ctx, rows = self.priced(28.2, 26.0)
        for side in ("HOME", "AWAY"):
            self.assertNotEqual(rows[("MONEYLINE", side)]["bet_status"], "BET")

    def test_without_paired_spread_moneyline_keeps_raw_margin(self):
        ml_only = [q for q in QUOTES if q["market"] == "MONEYLINE"]
        self.assertIsNone(card.anchored_spread_context(28.2, 26.0, ml_only, fit=FIT))
        rows = {r["side"]: r for r in card.price_game("g", 28.2, 26.0, ml_only)}
        self.assertAlmostEqual(rows["HOME"]["model_p"], round(card.phi(2.2 / card.COMBINED_SIGMA), 4), places=4)


class SdvScheduleAliasTest(unittest.TestCase):
    def test_sdv_2026_spellings_match_board_names(self):
        self.assertEqual(card._n("Hawai'i"), card._n("Hawaii"))
        self.assertEqual(card._n("App State"), card._n("Appalachian State"))


if __name__ == "__main__":
    unittest.main()
