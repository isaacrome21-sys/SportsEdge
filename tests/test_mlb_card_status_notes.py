"""The card's Status column says why a priced row is PASS.

Presentation only: these notes never change a status or a probability.
"""
import unittest

from sportsedge.mlb_myspari_own_model import render_markdown
from sportsedge.mlb_scored_card import EMPIRICAL_SIDE_CONFLICT_REASON, EV_FLOOR_REASON


def _row(status, codes=(), **extra):
    return {"game_id": "777", "market": "PITCHER_OUTS", "entity_id": "1", "entity_name": "Test Pitcher",
            "side": "OVER", "line": 14.5, "american_odds": -130, "fair_odds": -150, "ev_per_dollar": 0.01,
            "model_p_raw": 0.6, "push_p": 0.0, "model_p": 0.6, "edge": 0.03, "confidence_score": 60,
            "scored_status": status, "presentation_reason_codes": tuple(codes), **extra}


class CardStatusNoteTests(unittest.TestCase):
    def _status_cell(self, row):
        line = next(l for l in render_markdown([row], header="t").splitlines() if l.startswith("| 1 |"))
        return line.rstrip(" |").rsplit("|", 1)[-1].strip()

    def test_side_conflict_pass_is_explained(self):
        self.assertEqual(self._status_cell(_row("PASS", [EMPIRICAL_SIDE_CONFLICT_REASON])),
                         "PASS (prop opposes side play)")

    def test_ev_floor_pass_is_explained(self):
        self.assertEqual(self._status_cell(_row("PASS", [EV_FLOOR_REASON])), "PASS (EV < 2%)")

    def test_plain_pass_and_lean_get_no_note(self):
        self.assertEqual(self._status_cell(_row("PASS")), "PASS")
        self.assertEqual(self._status_cell(_row("LEAN", ["EMPIRICAL_PROP_LEAN_ONLY"])), "LEAN")


if __name__ == "__main__":
    unittest.main()
