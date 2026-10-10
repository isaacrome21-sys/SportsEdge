"""Sharp/consensus reference: exact line, two-sided, Pinnacle first, >=2 books else nothing."""
import unittest

from sportsedge.sports.cfb.sharp_reference import (
    attach_sharp_reference,
    peers_from_odds_api_events,
    reference_for,
    same_team,
)


class SharpReferenceTest(unittest.TestCase):
    def test_team_matching(self):
        self.assertTrue(same_team("Indiana", "Indiana Hoosiers"))
        self.assertTrue(same_team("Miami (OH)", "Miami OH"))
        self.assertFalse(same_team("Kansas", "Kansas State Wildcats"))
        self.assertFalse(same_team("Miami", "Miami (OH) RedHawks"))

    def test_pinnacle_preferred(self):
        peers = [{"book": "pinnacle", "spread": [-8.5, -105, -105]},
                 {"book": "fanduel", "spread": [-8.5, -120, 100]},
                 {"book": "betmgm", "spread": [-8.5, -120, 100]}]
        fp, method, books = reference_for(peers, "SPREAD", "AWAY", -8.5)
        self.assertAlmostEqual(fp, 0.5)
        self.assertEqual(books, ["pinnacle"])
        self.assertTrue(method.startswith("SHARP_BOOK"))

    def test_consensus_needs_two_books_same_line(self):
        one = [{"book": "fanduel", "total": [48.5, -110, -110]}]
        self.assertIsNone(reference_for(one, "TOTAL", "OVER", 48.5))
        diff_line = one + [{"book": "betmgm", "total": [49.5, -110, -110]}]
        self.assertIsNone(reference_for(diff_line, "TOTAL", "OVER", 48.5))
        two = one + [{"book": "betmgm", "total": [48.5, -110, -110]}]
        fp, method, books = reference_for(two, "TOTAL", "OVER", 48.5)
        self.assertAlmostEqual(fp, 0.5)
        self.assertEqual(method, "CONSENSUS_NO_VIG")

    def test_draftkings_never_its_own_reference(self):
        peers = [{"book": "draftkings", "ml": [-340, 270]}, {"book": "fanduel", "ml": [-330, 260]}]
        self.assertIsNone(reference_for(peers, "MONEYLINE", "AWAY", None))

    def test_home_spread_line_sign(self):
        peers = [{"book": "pinnacle", "spread": [-8.5, -110, -100]}]
        fp, _, _ = reference_for(peers, "SPREAD", "HOME", 8.5)
        self.assertLess(fp, 0.5)  # home +8.5 at -100 is the less likely side

    def test_attach_from_board_peers(self):
        board = [{"away": "Indiana", "home": "Nebraska",
                  "peers": [{"book": "pinnacle", "ml": [-300, 250]}]}]
        rows = [{"matchup": "Indiana @ Nebraska", "market": "MONEYLINE", "side": "HOME", "line": None},
                {"matchup": "Texas @ Oklahoma", "market": "MONEYLINE", "side": "HOME", "line": None}]
        self.assertEqual(attach_sharp_reference(rows, board), 1)
        self.assertIn("sharp_fair_p", rows[0])
        self.assertNotIn("sharp_fair_p", rows[1])

    def test_odds_api_events(self):
        ev = [{"away_team": "Indiana Hoosiers", "home_team": "Nebraska Cornhuskers", "bookmakers": [
            {"key": "pinnacle", "markets": [
                {"key": "spreads", "outcomes": [{"name": "Indiana Hoosiers", "point": -8.5, "price": -105},
                                                {"name": "Nebraska Cornhuskers", "point": 8.5, "price": -105}]},
                {"key": "totals", "outcomes": [{"name": "Over", "point": 48.5, "price": -110},
                                               {"name": "Under", "point": 48.5, "price": -110}]}]}]}]
        peers = peers_from_odds_api_events(ev, "Indiana", "Nebraska")
        self.assertEqual(peers[0]["spread"], [-8.5, -105, -105])
        self.assertEqual(peers[0]["total"], [48.5, -110, -110])
        self.assertEqual(peers_from_odds_api_events(ev, "Texas", "Oklahoma"), [])


if __name__ == "__main__":
    unittest.main()
