"""Fail-closed, exhaustive NFL card-market inventory tests."""
import unittest

from sportsedge.nfl_market_inventory_card import (
    market_inventory_section,
    quote_side_counts,
)


def _row(market, price, *, game="SF@ATL", reason=None):
    return {
        "market": market,
        "american_odds": price,
        "game_id": game,
        "reason": reason,
    }


class NFLMarketInventoryCardTests(unittest.TestCase):
    def test_all_51_catalog_markets_are_present_with_no_quote(self):
        page = market_inventory_section({"rows": []})
        self.assertIn("**51 market types**", page)
        self.assertIn("**3 research routes**", page)
        self.assertIn("**48 blocked model routes**", page)
        self.assertIn("| passing_yards | 0 | BLOCKED:NO_ENGINE | NO_QUOTE |", page)
        self.assertIn("| team_total | 0 | BLOCKED:NO_ENGINE | NO_QUOTE |", page)
        self.assertIn("| moneyline | 0 | RESEARCH_UNVALIDATED | NO_QUOTE |", page)
        self.assertNotIn("VERIFIED PLAY", page)

    def test_prop_quotes_count_both_sides_without_false_model_price(self):
        board = {"rows": [
            _row("passing_yards", -113), _row("passing_yards", -111),
            _row("moneyline", -148), _row("moneyline", 124),
            _row("first_half_total", -110),
        ]}
        page = market_inventory_section(board)
        self.assertIn("**3 catalog families**, **5 exact-price quote sides**", page)
        self.assertIn("| passing_yards | 2 | BLOCKED:NO_ENGINE | QUOTED_MODEL_BLOCKED:NO_ENGINE |", page)
        self.assertIn("| moneyline | 2 | RESEARCH_UNVALIDATED | QUOTED_RESEARCH_ONLY |", page)
        self.assertIn("| first_half_total | 1 | BLOCKED:NO_ENGINE | QUOTED_MODEL_BLOCKED:NO_ENGINE |", page)
        self.assertIn("not necessarily paired, fresh, or eligible", page)

    def test_placeholders_invalid_prices_and_unknown_markets_fail_closed(self):
        board = {"rows": [
            _row("passing_yards", -112.5),
            _row("passing_yards", True),
            _row("passing_yards", "-113"),
            _row("passing_yards", -113, game=None),
            _row("passing_yards", -113, reason="NO_QUOTE_OR_ENGINE_ROW"),
            _row("novel|market", 125),
        ]}
        self.assertEqual(quote_side_counts(board)["passing_yards"], 0)
        page = market_inventory_section(board)
        self.assertIn("novel&#124;market", page)
        self.assertIn("QUOTED_NO_CATALOG_MODEL", page)
        self.assertIn("| passing_yards | 0 | BLOCKED:NO_ENGINE | NO_QUOTE |", page)

    def test_malformed_board_rows_do_not_crash(self):
        self.assertIn("**51 market types**", market_inventory_section({"rows": "bad"}))
        self.assertIn("**51 market types**", market_inventory_section({"rows": [None, "bad", {}]}))


if __name__ == "__main__":
    unittest.main()
