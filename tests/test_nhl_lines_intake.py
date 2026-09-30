"""NHL phone intake fail-closed tests."""
from __future__ import annotations

import unittest

from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines
from scripts.render_nhl_myspari_card import NO_OWNER, reason_for


class IntakeTests(unittest.TestCase):
    def test_both_sides_required(self):
        with self.assertRaises(NhlLinesIntakeError):
            parse_nhl_lines("Rangers @ Bruins\nML +124")

    def test_parses_board(self):
        tickets = parse_nhl_lines("Rangers @ Bruins\nML +124 -148\nPL +1.5 -180 +150\nTotal 5.5 -110 -110")
        self.assertEqual(tickets[0].markets[0].market, "MONEYLINE")
        self.assertEqual(tickets[0].markets[1].market, "PUCK_LINE")
        self.assertEqual(tickets[0].markets[2].line, 5.5)


class CardTests(unittest.TestCase):
    def test_priced_markets_are_no_owner(self):
        self.assertEqual(reason_for("MONEYLINE"), NO_OWNER)
        self.assertEqual(reason_for("PUCK_LINE"), NO_OWNER)
        self.assertEqual(reason_for("TOTAL"), NO_OWNER)


if __name__ == "__main__":
    unittest.main()
