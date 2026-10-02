import unittest

from sportsedge.nfl_lines_intake import parse_nfl_lines
from sportsedge.nfl_props_side_totals import research_game_readout


class NflPropsSideTotals(unittest.TestCase):
    def test_intake_reads_team_total_and_prop(self):
        tickets = parse_nfl_lines(
            "Chiefs @ Ravens\n"
            "TT away 23.5 -115 -105\n"
            "prop Mahomes passing_yards 274.5 -110 -110\n"
        )
        self.assertEqual(tickets[0].markets[0].market, "team_total")
        self.assertEqual(tickets[0].markets[0].team_side, "away")
        self.assertEqual(tickets[0].markets[1].subject, "Mahomes")
        self.assertEqual(tickets[0].markets[1].market, "passing_yards")

    def test_research_readout_prices_sides_totals_and_blocks_props(self):
        rows = research_game_readout(
            {"margin": 2.5, "total": 47.0},
            [
                {"market": "moneyline", "line": None},
                {"market": "spread", "line": -3.5},
                {"market": "total", "line": 47.5},
                {"market": "team_total", "line": 24.5, "team_side": "home"},
                {"market": "passing_yards", "line": 274.5, "subject": "Mahomes"},
            ],
        )
        by_market = {row["market"]: row for row in rows}
        self.assertIsNone(by_market["team_total"]["no_model"])
        self.assertGreater(by_market["moneyline"]["sides"][0]["model_p"], 0.0)
        self.assertLess(by_market["spread"]["sides"][0]["model_p"], 1.0)
        self.assertEqual(by_market["passing_yards"]["no_model"], "NO_MODEL:ROLE_BUNDLE_REQUIRED")
        self.assertTrue(all(row["authority"] == "RESEARCH_READOUT_NOT_OFFICIAL" for row in rows))


if __name__ == "__main__":
    unittest.main()
