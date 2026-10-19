"""Unit tests for the anytime-TD engine arithmetic (frozen construction).

Run: python3 -m unittest test_nfl_atd_engine -v  (from this directory)
"""
import unittest

import atd_engine as eng


class TestShrinkage(unittest.TestCase):
    def test_shrunk_rate(self):
        # (2.0 + 10 * 0.15) / (6.0 + 10) = 3.5 / 16
        self.assertAlmostEqual(eng.shrunk_rate(2.0, 6.0, 0.15), 3.5 / 16.0)

    def test_shrink_toward_pool(self):
        # No TD evidence at all -> pulled toward the pool, below it by the
        # weight of the player's own scoreless games.
        p = eng.shrunk_rate(0.0, 8.0, 0.20)
        self.assertLess(p, 0.20)
        self.assertAlmostEqual(p, (0.0 + 10 * 0.20) / 18.0)

    def test_recency_weights(self):
        w = eng.recency_weights(9)
        self.assertEqual(w[0], 1.0)
        self.assertAlmostEqual(w[8], 0.5)  # 8-game half-life
        self.assertTrue(all(w[i] > w[i + 1] for i in range(8)))


class TestOddsAndRules(unittest.TestCase):
    def test_raw_implied(self):
        self.assertAlmostEqual(eng.raw_implied(-230), 230 / 330)
        self.assertAlmostEqual(eng.raw_implied(600), 100 / 700)
        self.assertAlmostEqual(eng.raw_implied(-100), 0.5)
        with self.assertRaises(ValueError):
            eng.raw_implied(0)

    def test_rule1_boundary_is_pass(self):
        # YES iff model_p > implied, strictly (locked Rule 1).
        data = {"by_player": {}, "by_season": {}, "meta": {}}
        # Build a stub through price_board_row with a fixed engine price:
        orig = eng.price_player
        try:
            eng.price_player = lambda d, pid, s, w, pool_cache=None: {
                "status": "PRICED", "model_p": 0.25, "prior_games": 9,
                "weighted_games": 7.0, "pool_rate": 0.2,
                "pool_source": "TEST", "position_group": "RB"}
            row = {"game_id": "g", "player_name": "X Y", "player_id": "p1",
                   "game_teams": ["DAL", "GB"], "yes_price": 300,
                   "captured_at": "t", "kickoff": "k", "season": 2026,
                   "week": 7}
            out = eng.price_board_row(data, {}, row)
            self.assertAlmostEqual(out["raw_implied"], 0.25)
            self.assertEqual(out["selection"], "PASS")  # tie -> PASS
            self.assertAlmostEqual(out["edge"], 0.0)     # Rule 9 descriptive
        finally:
            eng.price_player = orig

    def test_not_a_player_row(self):
        self.assertTrue(eng.is_not_a_player_row("GB Packers D/ST"))
        self.assertTrue(eng.is_not_a_player_row("No Touchdown Scorer"))
        self.assertFalse(eng.is_not_a_player_row("CeeDee Lamb"))


class TestGateAndNames(unittest.TestCase):
    def _data(self, apps):
        return {"by_player": {"p1": apps}, "by_season": {}, "meta": {}}

    def test_insufficient_games(self):
        apps = [{"season": 2025, "week": w, "pid": "p1",
                 "position_group": "RB", "team": "DAL", "opp": "GB",
                 "td": 0, "st_td": 0} for w in (14, 15, 16)]
        out = eng.price_player(self._data(apps), "p1", 2026, 7)
        self.assertEqual(out["status"], "UNPRICED")
        self.assertEqual(out["reason"], "UNPRICED_INSUFFICIENT_GAMES")
        self.assertEqual(out["prior_games"], 3)

    def test_evidence_window_excludes_old_seasons(self):
        apps = [{"season": 2023, "week": w, "pid": "p1",
                 "position_group": "RB", "team": "DAL", "opp": "GB",
                 "td": 1, "st_td": 0} for w in range(1, 18)]
        # Target in 2025: only 2024+2025 count -> zero evidence -> gated.
        out = eng.price_player(self._data(apps), "p1", 2025, 3)
        self.assertEqual(out["reason"], "UNPRICED_INSUFFICIENT_GAMES")
        self.assertEqual(out["prior_games"], 0)

    def test_normalize_name(self):
        self.assertEqual(eng.normalize_name("Pierre Strong Jr."), "pierre strong")
        self.assertEqual(eng.normalize_name("Amon-Ra St. Brown"), "amon ra st brown")
        self.assertEqual(eng.normalize_name("MarShawn Lloyd"), "marshawn lloyd")


if __name__ == "__main__":
    unittest.main()
