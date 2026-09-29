import unittest

from sportsedge.mlb_myspari_own_model import (
    OPPOSITE_TEAM_OUTCOME_REASON,
    SAME_SIDE_STACK_REASON,
    SCRIPT_CONFLICT_REASON,
    TEAM_SCORING_CONFLICT_REASON,
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
    def test_directions_are_diagnostic_only(self):
        self.assertEqual(run_script_direction(_row("TOTALS", "OVER", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("TEAM_TOTALS", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_OUTS", "OVER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_HITS_ALLOWED", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("NRFI", "YES", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("YRFI", "YES", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("MONEYLINE", "HOME", 0.1)), 0)

    def test_global_script_labels_no_longer_demote_independent_rows(self):
        over = _row("TOTALS", "OVER", 0.02, line=7.5)
        strikeouts = _row(
            "PITCHER_K", "OVER", 0.18, line=4.5,
            entity="pitcher-home", team_side="HOME",
        )
        walks = _row(
            "PITCHER_BB", "OVER", 0.40, line=1.5,
            entity="pitcher-away", team_side="AWAY",
        )
        apply_same_game_guard([over, strikeouts, walks])
        self.assertEqual([over["status"], strikeouts["status"], walks["status"]], ["ACTIONABLE"] * 3)

    def test_same_team_full_over_and_f5_under_conflict(self):
        full_over = _row(
            "TEAM_TOTALS", "OVER", 0.25, line=3.5, score=100,
            entity="padres", team_side="HOME",
        )
        f5_under = _row(
            "F5_TEAM_TOTALS", "UNDER", 0.04, line=1.5, score=60,
            entity="padres", team_side="HOME",
        )
        apply_same_game_guard([full_over, f5_under])
        self.assertEqual(full_over["status"], "ACTIONABLE")
        self.assertEqual(f5_under["status"], "PASS")
        self.assertIn(TEAM_SCORING_CONFLICT_REASON, f5_under["presentation_reason_codes"])

    def test_team_total_over_conflicts_with_opposing_pitcher_outs_over(self):
        yankees_over = _row(
            "TEAM_TOTALS", "OVER", 0.30, line=3.5, score=100,
            entity="yankees", team_side="HOME",
        )
        tolle_outs_over = _row(
            "PITCHER_OUTS", "OVER", 0.20, line=16.5, score=60,
            entity="tolle", team_side="AWAY", name="Payton Tolle",
        )
        apply_same_game_guard([yankees_over, tolle_outs_over])
        self.assertEqual(yankees_over["status"], "ACTIONABLE")
        self.assertEqual(tolle_outs_over["status"], "PASS")
        self.assertIn(TEAM_SCORING_CONFLICT_REASON, tolle_outs_over["presentation_reason_codes"])

    def test_pitcher_strikeout_over_does_not_conflict_with_team_or_game_over(self):
        game_over = _row("TOTALS", "OVER", 0.12, line=7.5, score=100)
        padres_over = _row(
            "TEAM_TOTALS", "OVER", 0.18, line=3.5, score=100,
            entity="padres", team_side="HOME",
        )
        king_k_over = _row(
            "PITCHER_K", "OVER", 0.18, line=4.5, score=60,
            entity="king", team_side="HOME", name="Michael King",
        )
        apply_same_game_guard([game_over, padres_over, king_k_over])
        self.assertEqual([r["status"] for r in (game_over, padres_over, king_k_over)], ["ACTIONABLE"] * 3)

    def test_same_direction_team_total_and_opposing_pitcher_allowance_can_coexist(self):
        padres_over = _row(
            "TEAM_TOTALS", "OVER", 0.18, line=3.5, score=100,
            entity="padres", team_side="HOME",
        )
        boyd_hits_over = _row(
            "PITCHER_HITS_ALLOWED", "OVER", 0.25, line=4.5, score=60,
            entity="boyd", team_side="AWAY", name="Matthew Boyd",
        )
        apply_same_game_guard([padres_over, boyd_hits_over])
        self.assertEqual(padres_over["status"], "ACTIONABLE")
        self.assertEqual(boyd_hits_over["status"], "ACTIONABLE")

    def test_team_total_does_not_conflict_with_own_pitcher_prop(self):
        padres_over = _row(
            "TEAM_TOTALS", "OVER", 0.18, line=3.5, score=100,
            entity="padres", team_side="HOME",
        )
        king_outs_over = _row(
            "PITCHER_OUTS", "OVER", 0.25, line=14.5, score=60,
            entity="king", team_side="HOME", name="Michael King",
        )
        apply_same_game_guard([padres_over, king_outs_over])
        self.assertEqual(padres_over["status"], "ACTIONABLE")
        self.assertEqual(king_outs_over["status"], "ACTIONABLE")

    def test_unbound_scoring_rows_fail_neutral(self):
        team_over = _row("TEAM_TOTALS", "OVER", 0.18, line=3.5, score=100, entity="padres")
        outs_over = _row("PITCHER_OUTS", "OVER", 0.25, line=14.5, score=60, entity="boyd")
        apply_same_game_guard([team_over, outs_over])
        self.assertEqual(team_over["status"], "ACTIONABLE")
        self.assertEqual(outs_over["status"], "ACTIONABLE")

    def test_direct_opposite_same_contract_keeps_best_ev(self):
        over = _row("TOTALS", "OVER", 0.08, line=7.5)
        under = _row("TOTALS", "UNDER", 0.02, line=7.5)
        apply_same_game_guard([over, under])
        self.assertEqual(over["status"], "ACTIONABLE")
        self.assertEqual(under["status"], "PASS")
        self.assertIn(SCRIPT_CONFLICT_REASON, under["presentation_reason_codes"])

    def test_direct_opposite_run_line_uses_negated_line(self):
        away = _row("RUN_LINE", "AWAY", 0.04, line=-1.5)
        home = _row("RUN_LINE", "HOME", 0.01, line=1.5)
        apply_same_game_guard([away, home])
        self.assertEqual(away["status"], "ACTIONABLE")
        self.assertEqual(home["status"], "PASS")
        self.assertIn(SCRIPT_CONFLICT_REASON, home["presentation_reason_codes"])

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

    def test_unbound_pitcher_win_fails_neutral(self):
        away_ml = _row("MONEYLINE", "AWAY", 0.04, score=96)
        pitcher_win = _row("PITCHER_RECORD_WIN", "YES", 0.43, score=56, entity="p1")
        apply_same_game_guard([away_ml, pitcher_win])
        self.assertEqual(away_ml["status"], "ACTIONABLE")
        self.assertEqual(pitcher_win["status"], "ACTIONABLE")

    def test_other_games_and_pass_rows_untouched(self):
        a = _row("TOTALS", "OVER", 0.1, game="g1")
        b = _row("TOTALS", "UNDER", 0.2, game="g2")
        c = _row("TOTALS", "UNDER", 0.5, game="g1", status="PASS")
        apply_same_game_guard([a, b, c])
        self.assertEqual((a["status"], b["status"], c["status"]), ("ACTIONABLE", "ACTIONABLE", "PASS"))
        self.assertNotIn("presentation_reason_codes", c)

    def test_missing_game_id_rows_do_not_conflict(self):
        a = _row("TOTALS", "OVER", 0.1, game=None)
        b = _row("TOTALS", "UNDER", 0.2, game=None)
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
