import pytest

from sportsedge.draftkings_game_market_source import (
    DraftKingsGameMarketError,
    board_url,
    game_line_category_id,
)


def test_live_verified_categories_are_league_scoped():
    assert game_line_category_id("baseball_mlb") == 493
    assert game_line_category_id("americanfootball_nfl") == 492
    assert board_url("baseball_mlb").endswith("/leagues/84240/categories/493")
    assert board_url("americanfootball_nfl").endswith("/leagues/88808/categories/492")


def test_unverified_cfb_category_fails_closed():
    with pytest.raises(DraftKingsGameMarketError, match="DK_GAME_CATEGORY_UNVERIFIED"):
        board_url("americanfootball_ncaaf")
