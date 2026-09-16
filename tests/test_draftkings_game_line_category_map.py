import unittest

from sportsedge.draftkings_game_market_source import DraftKingsGameMarketError, board_url, game_line_category_id


class DraftKingsGameLineCategoryMapTest(unittest.TestCase):
    def test_live_verified_categories_are_league_scoped(self):
        self.assertEqual(game_line_category_id("baseball_mlb"), 493)
        self.assertEqual(game_line_category_id("americanfootball_nfl"), 492)
        self.assertTrue(board_url("baseball_mlb").endswith("/leagues/84240/categories/493"))
        self.assertTrue(board_url("americanfootball_nfl").endswith("/leagues/88808/categories/492"))

    def test_unverified_cfb_category_fails_closed(self):
        with self.assertRaisesRegex(DraftKingsGameMarketError, "DK_GAME_CATEGORY_UNVERIFIED"):
            board_url("americanfootball_ncaaf")


if __name__ == "__main__":
    unittest.main()
