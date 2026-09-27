import unittest

from sportsedge.draftkings_game_market_source import DraftKingsGameMarketError, board_url, game_line_category_id


class DraftKingsGameLineCategoryMapTest(unittest.TestCase):
    def test_live_verified_categories_are_league_scoped(self):
        self.assertEqual(game_line_category_id("baseball_mlb"), 493)
        self.assertEqual(game_line_category_id("americanfootball_nfl"), 492)
        self.assertEqual(game_line_category_id("americanfootball_ncaaf"), 492)
        self.assertTrue(board_url("baseball_mlb").endswith("/leagues/84240/categories/493"))
        self.assertTrue(board_url("americanfootball_nfl").endswith("/leagues/88808/categories/492"))
        self.assertTrue(board_url("americanfootball_ncaaf").endswith("/leagues/87637/categories/492"))

    def test_unknown_sport_fails_closed(self):
        with self.assertRaisesRegex(DraftKingsGameMarketError, "DK_GAME_SPORT_UNSUPPORTED"):
            board_url("unknown_sport")


if __name__ == "__main__":
    unittest.main()
