"""#1968 guard: postseason PITCHER_K / PITCHER_OUTS are blocked on the canonical card (pre-registered #1967)."""
from types import SimpleNamespace

import pytest

from sportsedge.generic_card_pipeline import POSTSEASON_BIASED_PITCHER_MARKETS, _model_input


def _make(market, **metadata):
    game = SimpleNamespace(game_pk=123, game_type=metadata.pop("bound_type", None),
                           away_probable_pitcher_id=700, home_probable_pitcher_id=800)
    quote = {"market": market, "entity_id": "700", "line": 4.5, "side": "OVER"}
    feature = {"game_pk": 123, "entity_id": "700", "market": market,
               "features": {"history": [5, 6, 4, 7, 5]}, **metadata}
    return game, quote, feature


def _call(game, quote, feature):
    return _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)


def test_guard_covers_exactly_the_tested_markets():
    assert set(POSTSEASON_BIASED_PITCHER_MARKETS) == {"PITCHER_K", "PITCHER_OUTS"}
    assert all("#1968" in r for r in POSTSEASON_BIASED_PITCHER_MARKETS.values())


@pytest.mark.parametrize("market", ["PITCHER_K", "PITCHER_OUTS"])
@pytest.mark.parametrize("game_type", ["F", "D", "L", "W", "P"])
def test_postseason_feature_game_type_blocks(market, game_type):
    game, quote, feature = _make(market, game_type=game_type)
    with pytest.raises(ValueError, match=f"MLB_POSTSEASON_{market}_BIASED"):
        _call(game, quote, feature)


@pytest.mark.parametrize("market", ["PITCHER_K", "PITCHER_OUTS"])
def test_bound_live_game_type_blocks_even_without_feature_metadata(market):
    game, quote, feature = _make(market, bound_type="L")
    with pytest.raises(ValueError, match="_BIASED \\(#1968\\)"):
        _call(game, quote, feature)


@pytest.mark.parametrize("market", ["PITCHER_K", "PITCHER_OUTS"])
def test_any_postseason_signal_wins_over_regular_label(market):
    game, quote, feature = _make(market, bound_type="D", game_type="R", rules_mode="REGULAR_SEASON")
    with pytest.raises(ValueError, match="_BIASED"):
        _call(game, quote, feature)
    game, quote, feature = _make(market, rules_mode="POSTSEASON")
    with pytest.raises(ValueError, match="_BIASED"):
        _call(game, quote, feature)


@pytest.mark.parametrize("market", ["PITCHER_K", "PITCHER_OUTS"])
def test_regular_season_rows_are_unchanged(market):
    game, quote, feature = _make(market, bound_type="R", game_type="R")
    legacy_game, legacy_quote, legacy_feature = _make(market)
    assert _call(game, quote, feature) == _call(legacy_game, legacy_quote, legacy_feature)


@pytest.mark.parametrize("market", ["PITCHER_BB", "PITCHER_ER", "PITCHER_HITS_ALLOWED"])
def test_other_pitcher_markets_are_not_touched_by_this_guard(market):
    game, quote, feature = _make(market, bound_type="D")
    try:
        _call(game, quote, feature)
    except ValueError as exc:
        assert "_BIASED" not in str(exc)
