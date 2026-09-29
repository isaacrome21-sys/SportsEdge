import unittest

from sportsedge.mlb_myspari_own_model import (
    SAME_SIDE_STACK_REASON,
    SCRIPT_CONFLICT_REASON,
    apply_same_game_guard,
    run_script_direction,
)


def _row(market, side, ev, game="g1", status="ACTIONABLE", line=0.0, entity_id=None):
    return {"game_id": game, "market": market, "side": side, "line": line,
            "ev_per_dollar": ev, "status": status,
            "entity_id": game if entity_id is None else entity_id}


class SameGameGuardTest(unittest.TestCase):
    def test_directions_remain_diagnostic_only(self):
        self.assertEqual(run_script_direction(_row("TOTALS", "OVER", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("TEAM_TOTALS", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_OUTS", "OVER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("PITCHER_HITS_ALLOWED", "UNDER", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("NRFI", "YES", 0.1)), -1)
        self.assertEqual(run_script_direction(_row("YRFI", "YES", 0.1)), 1)
        self.assertEqual(run_script_direction(_row("MONEYLINE", "HOME", 0.1)), 0)

    def test_cross_market_script_labels_do_not_demote_independent_rows(self):
        over = _row("TOTALS", "OVER", 0.02, line=7.5)
        tt = _row("TEAM_TOTALS", "UNDER", 0.30, line=3.5, entity_id="team")
        outs = _row("PITCHER_OUTS", "OVER", 0.20, line=16.5, entity_id="pitcher-a")
        strikeouts = _row("PITCHER_K", "OVER", 0.18, line=4.5, entity_id="pitcher-b")
        walks = _row("PITCHER_BB", "OVER", 0.40, line=1.5, entity_id="pitcher-c")
        apply_same_game_guard([over, tt, outs, strikeouts, walks])
        self.assertEqual(
            [over["status"], tt["status"], outs["status"], strikeouts["status"], walks["status"]],
            ["ACTIONABLE"] * 5,
        )
        for row in (over, tt, outs, strikeouts, walks):
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

    def test_ml_and_run_line_same_team_is_one_bet(self):
        ml = _row("MONEYLINE", "HOME", 0.136)
        rl = _row("RUN_LINE", "HOME", 0.142, line=-1.5)
        apply_same_game_guard([ml, rl])
        self.assertEqual(rl["status"], "ACTIONABLE")
        self.assertEqual(ml["status"], "PASS")
        self.assertIn(SAME_SIDE_STACK_REASON, ml["presentation_reason_codes"])

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
