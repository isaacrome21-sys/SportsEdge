import unittest

from sportsedge.mlb_myspari_own_model import (
    OPPOSITE_TEAM_OUTCOME_REASON,
    SAME_SIDE_STACK_REASON,
    SCRIPT_CONFLICT_REASON,
    apply_same_game_guard,
    myspari_rows,
    run_script_direction,
)
from sportsedge.mlb_scored_card import EV_FLOOR_REASON, MIN_CARD_EV


def _row(market, side, ev, game="g1", status="ACTIONABLE", line=0.0,
         score=50, entity=None, team_side=None, name=""):
    return {
        "game_id": game,
        "market": market,
        "side": side,
        "line": line,
        "ev_per_dollar": ev,
        "confidence_score": score,
        "status": status,
        "entity_id": game if entity is None else entity,
        "entity_name": name,
        "team_side": team_side,
    }


def _engine_pair(p_over, over_odds, under_odds):
    base = {
        "game_id": "g",
        "market": "TOTALS",
        "entity_id": "g",
        "line": 7.5,
        "mc_paths": 100000,
        "bet_status": "MODEL_CANDIDATE",
    }
    return [
        {**base, "side": "OVER", "american_odds": over_odds, "model_p": p_over},
        {**base, "side": "UNDER", "american_odds": under_odds, "model_p": 1 - p_over},
    ]


class SameGameGuardTest(unittest.TestCase):
    def test_directions(self):
        self.assertEqual(run_script_direction(_row("TOTALS", "OVER", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("TEAM_TOTALS", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_OUTS", "OVER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_HITS_ALLOWED", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("NRFI", "YES", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("YRFI", "YES", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("MONEYLINE", "HOME", 0.1)), 0)

    def test_over_vs_pitcher_outs_keeps_best_ev_script(self):
        over = _row("TOTALS", "OVER", 0.02, line=6.0)
        tt = _row("TEAM_TOTALS", "OVER", 0.30, line=3.5)
        outs = _row("PITCHER_OUTS", "OVER", 0.20, line=16.5)
        apply_same_game_guard([over, tt, outs])
        self.assertEqual(over["status"], "ACTIONABLE")
        self.assertEqual(tt["status"], "ACTIONABLE")
        self.assertEqual(outs["status"], "PASS")
        self.assertIn(SCRIPT_CONFLICT_REASON, outs["presentation_reason_codes"])

    def test_full_game_and_f5_same_team_collapse_to_one_outcome(self):
        ml = _row("MONEYLINE", "AWAY", 0.04, score=96)
        f5_ml = _row("F5_MONEYLINE", "AWAY", 0.06, score=56)
        f5_rl = _row("F5_RUN_LINE", "AWAY", 0.08, line=0.5, score=56)
        apply_same_game_guard([ml, f5_ml, f5_rl])
        self.assertEqual(ml["status"], "ACTIONABLE")
        self.assertEqual(f5_ml["status"], "PASS")
        self.assertEqual(f5_rl["status"], "PASS")
        self.assertIn(SAME_SIDE_STACK_REASON, f5_ml["presentation_reason_codes"])
        self.assertIn(SAME_SIDE_STACK_REASON, f5_rl["presentation_reason_codes"])

    def test_pitcher_win_opposite_team_conflicts_when_team_bound(self):
        away_ml = _row("MONEYLINE", "AWAY", 0.04, score=96)
        home_pitcher_win = _row(
            "PITCHER_RECORD_WIN", "YES", 0.40, score=56,
            entity="650633", team_side="HOME", name="Michael King",
        )
        apply_same_game_guard([away_ml, home_pitcher_win])
        self.assertEqual(away_ml["status"], "ACTIONABLE")
        self.assertEqual(home_pitcher_win["status"], "PASS")
        self.assertIn(OPPOSITE_TEAM_OUTCOME_REASON, home_pitcher_win["presentation_reason_codes"])

    def test_pitcher_win_same_team_is_duplicate_when_team_bound(self):
        away_ml = _row("MONEYLINE", "AWAY", 0.04, score=96)
        away_pitcher_win = _row(
            "PITCHER_RECORD_WIN", "YES", 0.43, score=56,
            entity="571510", team_side="AWAY", name="Matthew Boyd",
        )
        apply_same_game_guard([away_ml, away_pitcher_win])
        self.assertEqual(away_ml["status"], "ACTIONABLE")
        self.assertEqual(away_pitcher_win["status"], "PASS")
        self.assertIn(SAME_SIDE_STACK_REASON, away_pitcher_win["presentation_reason_codes"])

    def test_exact_cubs_padres_outcome_stack_collapses_to_one_play(self):
        # Sept. 29 board: Cubs ML/F5 ML/F5 +0.5, Boyd to win (Cubs), King to win (Padres).
        # Current policy keeps the strongest qualification score first, then EV.
        cubs_ml = _row("MONEYLINE", "AWAY", 0.036, score=96)
        cubs_f5_ml = _row("F5_MONEYLINE", "AWAY", 0.008, score=56)
        cubs_f5_rl = _row("F5_RUN_LINE", "AWAY", 0.007, line=0.5, score=56)
        king_win = _row(
            "PITCHER_RECORD_WIN", "YES", 0.051, score=56,
            entity="650633", team_side="HOME", name="Michael King",
        )
        boyd_win = _row(
            "PITCHER_RECORD_WIN", "YES", 0.073, score=56,
            entity="571510", team_side="AWAY", name="Matthew Boyd",
        )
        rows = [cubs_ml, cubs_f5_ml, cubs_f5_rl, king_win, boyd_win]
        apply_same_game_guard(rows)
        self.assertEqual([r["status"] for r in rows].count("ACTIONABLE"), 1)
        self.assertEqual(cubs_ml["status"], "ACTIONABLE")
        self.assertIn(OPPOSITE_TEAM_OUTCOME_REASON, king_win["presentation_reason_codes"])
        self.assertIn(SAME_SIDE_STACK_REASON, cubs_f5_ml["presentation_reason_codes"])
        self.assertIn(SAME_SIDE_STACK_REASON, cubs_f5_rl["presentation_reason_codes"])
        self.assertIn(SAME_SIDE_STACK_REASON, boyd_win["presentation_reason_codes"])

    def test_unbound_pitcher_win_fails_neutral(self):
        away_ml = _row("MONEYLINE", "AWAY", 0.04, score=96)
        pitcher_win = _row("PITCHER_RECORD_WIN", "YES", 0.43, score=56, entity="p1")
        apply_same_game_guard([away_ml, pitcher_win])
        self.assertEqual(away_ml["status"], "ACTIONABLE")
        self.assertEqual(pitcher_win["status"], "ACTIONABLE")

    def test_other_games_and_pass_rows_untouched(self):
        a = _row("TOTALS", "OVER", 0.1, game="g1")
        b = _row("PITCHER_OUTS", "OVER", 0.2, game="g2")
        c = _row("PITCHER_OUTS", "OVER", 0.5, game="g1", status="PASS")
        apply_same_game_guard([a, b, c])
        self.assertEqual((a["status"], b["status"], c["status"]), ("ACTIONABLE", "ACTIONABLE", "PASS"))
        self.assertNotIn("presentation_reason_codes", c)

    def test_missing_game_id_rows_do_not_conflict(self):
        a = _row("TOTALS", "OVER", 0.1, game=None)
        b = _row("PITCHER_OUTS", "OVER", 0.2, game=None)
        apply_same_game_guard([a, b])
        self.assertEqual((a["status"], b["status"]), ("ACTIONABLE", "ACTIONABLE"))


class CardEvFloorTest(unittest.TestCase):
    def _over(self, rows):
        return next(r for r in rows if r["side"] == "OVER")

    def test_positive_edge_but_near_zero_return_is_not_a_play(self):
        over = self._over(myspari_rows({"results": _engine_pair(0.546, -120, 100)}))
        self.assertGreater(over["edge"], 0)
        self.assertLess(over["ev_per_dollar"], MIN_CARD_EV)
        self.assertEqual(over["scored_status"], "PASS")
        self.assertIn(EV_FLOOR_REASON, over["presentation_reason_codes"])

    def test_clear_return_stays_actionable(self):
        over = self._over(myspari_rows({"results": _engine_pair(0.58, -102, -118)}))
        self.assertGreaterEqual(over["ev_per_dollar"], MIN_CARD_EV)
        self.assertEqual(over["scored_status"], "ACTIONABLE")

    def test_floor_never_changes_probability_or_score(self):
        over = self._over(myspari_rows({"results": _engine_pair(0.546, -120, 100)}))
        self.assertAlmostEqual(over["model_p"], 0.546, places=9)
        self.assertGreater(over["confidence_score"], 0)


if __name__ == "__main__":
    unittest.main()
