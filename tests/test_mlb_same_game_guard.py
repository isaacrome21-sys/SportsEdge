import unittest

from sportsedge.mlb_myspari_own_model import (
    SAME_SIDE_STACK_REASON,
    SCRIPT_CONFLICT_REASON,
    apply_same_game_guard,
    run_script_direction,
)


def _row(market, side, ev, game="g1", status="ACTIONABLE", line=0.0):
    return {"game_id": game, "market": market, "side": side, "line": line,
            "ev_per_dollar": ev, "status": status, "entity_id": game}


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

    def test_ml_and_run_line_same_team_is_one_bet(self):
        ml = _row("MONEYLINE", "HOME", 0.136)
        rl = _row("RUN_LINE", "HOME", 0.142, line=-1.5)
        apply_same_game_guard([ml, rl])
        self.assertEqual(rl["status"], "ACTIONABLE")
        self.assertEqual(ml["status"], "PASS")
        self.assertIn(SAME_SIDE_STACK_REASON, ml["presentation_reason_codes"])

    def test_missing_game_ids_are_fail_neutral(self):
        # Unknown game identity must never create a synthetic shared same-game bucket.
        high = _row("TOTALS", "OVER", 0.20, game=None)
        quiet = _row("PITCHER_OUTS", "OVER", 0.30, game=None)
        apply_same_game_guard([high, quiet])
        self.assertEqual((high["status"], quiet["status"]), ("ACTIONABLE", "ACTIONABLE"))
        self.assertNotIn("presentation_reason_codes", high)
        self.assertNotIn("presentation_reason_codes", quiet)

    def test_other_games_and_pass_rows_untouched(self):
        a = _row("TOTALS", "OVER", 0.1, game="g1")
        b = _row("PITCHER_OUTS", "OVER", 0.2, game="g2")
        c = _row("PITCHER_OUTS", "OVER", 0.5, game="g1", status="PASS")
        apply_same_game_guard([a, b, c])
        self.assertEqual((a["status"], b["status"], c["status"]), ("ACTIONABLE", "ACTIONABLE", "PASS"))
        self.assertNotIn("presentation_reason_codes", c)


if __name__ == "__main__":
    unittest.main()