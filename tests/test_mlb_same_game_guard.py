import unittest

from sportsedge.mlb_myspari_own_model import (
    OPPOSITE_TEAM_OUTCOME_REASON,
    SAME_SIDE_STACK_REASON,
    SCRIPT_CONFLICT_REASON,
    apply_same_game_guard,
    run_script_direction,
)


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


class SameGameGuardTest(unittest.TestCase):
    def test_directions_are_diagnostic_only(self):
        self.assertEqual(run_script_direction(_row("TOTALS", "OVER", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("TEAM_TOTALS", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_OUTS", "OVER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_HITS_ALLOWED", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("NRFI", "YES", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("YRFI", "YES", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("MONEYLINE", "HOME", 0.1)), 0)

    def test_cross_market_script_labels_do_not_demote_independent_rows(self):
        over = _row("TOTALS", "OVER", 0.02, line=7.5)
        tt_under = _row("TEAM_TOTALS", "UNDER", 0.30, line=3.5, entity="team-home")
        outs = _row("PITCHER_OUTS", "OVER", 0.20, line=16.5, entity="pitcher-a")
        strikeouts = _row("PITCHER_K", "OVER", 0.18, line=4.5, entity="pitcher-b")
        walks = _row("PITCHER_BB", "OVER", 0.40, line=1.5, entity="pitcher-c")
        apply_same_game_guard([over, tt_under, outs, strikeouts, walks])
        self.assertEqual(
            [over["status"], tt_under["status"], outs["status"], strikeouts["status"], walks["status"]],
            ["ACTIONABLE"] * 5,
        )
        for row in (over, tt_under, outs, strikeouts, walks):
            self.assertNotIn("guard_kept_instead", row)

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


if __name__ == "__main__":
    unittest.main()
