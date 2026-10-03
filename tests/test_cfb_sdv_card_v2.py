import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "cfb_sdv_card_v2",
    Path(__file__).resolve().parents[1] / "scripts" / "run_cfb_sdv_card_v2.py",
)
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)


class BlockedCardTest(unittest.TestCase):
    def test_floor_and_same_game_guard(self):
        rows = card.price_game("g", 25.0, 24.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 120},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -140},
            {"market": "SPREAD", "side": "HOME", "line": 1.5, "american_odds": -110},
            {"market": "SPREAD", "side": "AWAY", "line": -1.5, "american_odds": -110},
        ], validated={"MONEYLINE", "SPREAD", "TOTAL"})
        bets = [r for r in rows if r["bet_status"] == "BET"]
        self.assertEqual(len(bets), 1)
        self.assertTrue(any(r["reason"] == "SAME_GAME_GUARD" for r in rows))

    def test_paired_devig_sums_to_one(self):
        rows = card.price_game("g", 28.0, 24.0, [
            {"market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110},
            {"market": "SPREAD", "side": "AWAY", "line": 3.5, "american_odds": -110},
        ])
        self.assertAlmostEqual(rows[0]["market_p"] + rows[1]["market_p"], 1.0, places=3)
        self.assertEqual(rows[0]["devig"], "PAIRED_PROPORTIONAL")
        self.assertAlmostEqual(rows[0]["model_p"] + rows[1]["model_p"], 1.0, places=3)

    def test_total_symmetry(self):
        rows = card.price_game("g", 30.0, 22.5, [
            {"market": "TOTAL", "side": "OVER", "line": 52.5, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 52.5, "american_odds": -110},
        ])
        self.assertAlmostEqual(rows[0]["model_p"], 0.5, places=3)

    def test_compact_expand_and_resolve(self):
        from types import SimpleNamespace as G
        row = card.expand_compact({"away": "Mississippi", "home": "Alabama",
                                   "ml": [180, -218], "spread": [5.5, -112, -108], "total": [61.5, -105, -115]})
        self.assertEqual(len(row["quotes"]), 6)
        self.assertEqual(row["quotes"][3]["line"], -5.5)
        games = [G(game_id="1", away_team="Ole Miss", home_team="Alabama"),
                 G(game_id="2", away_team="Massachusetts", home_team="Ohio")]
        self.assertEqual(card.resolve_game(row, games).game_id, "1")
        self.assertEqual(card.resolve_game({"away": "UMass", "home": "Ohio"}, games).game_id, "2")

    def test_moment_match_and_sanity(self):
        snaps = {f"T{i}": {"prior": {k: float(i) for k in card.TEAM_KEYS},
                           "current": {k: float(i) * 2 for k in card.TEAM_KEYS}} for i in range(30)}
        moments = {k: (0.5, 0.1) for k in card.TEAM_KEYS}
        card.moment_match(snaps, moments)
        vals = [snaps[t]["current"]["explosive_rate"] for t in snaps]
        mu = sum(vals) / len(vals)
        self.assertAlmostEqual(mu, 0.5, places=6)
        self.assertLess(snaps["T0"]["current"]["explosive_rate"], snaps["T29"]["current"]["explosive_rate"])
        self.assertFalse(card.projection_sane(160.0, 150.0, []))
        self.assertTrue(card.projection_sane(30.0, 24.0, [{"market": "TOTAL", "line": 52.5}]))

    def test_edge_cap(self):
        rows = card.price_game("g", 45.0, 10.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 200},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -250}])
        self.assertEqual(rows[0]["reason"], "EDGE_TOO_LARGE_SUSPECT")
        self.assertEqual(rows[0]["bet_status"], "PASS")

    def test_unvalidated_edges_are_leans(self):
        quotes = [{"market": "MONEYLINE", "side": "HOME", "american_odds": 120},
                  {"market": "MONEYLINE", "side": "AWAY", "american_odds": -140},
                  {"market": "SPREAD", "side": "HOME", "line": 1.5, "american_odds": -110},
                  {"market": "SPREAD", "side": "AWAY", "line": -1.5, "american_odds": -110}]
        rows = card.price_game("g", 25.0, 24.0, quotes)
        self.assertFalse(any(r["bet_status"] == "BET" for r in rows))
        leans = [r for r in rows if r["bet_status"] == "LEAN"]
        self.assertEqual(len(leans), 1)
        self.assertEqual(leans[0]["reason"], "MODEL_EDGE_NOT_VALIDATED_VS_CLOSE")
        self.assertEqual(card.VALIDATED_MARKETS, frozenset())


if __name__ == "__main__":
    unittest.main()
