"""Postseason metadata must not enter frozen legacy MLB game pricing."""
from types import SimpleNamespace

import pytest

from sportsedge.generic_card_pipeline import _model_input


def _make(*, market="MONEYLINE", **metadata):
    game = SimpleNamespace(game_pk=123, game_type=metadata.pop("bound_type", None))
    quote = {"market": market, "entity_id": "game", "line": 0.0, "side": "HOME"}
    feature = {"game_pk": 123, "entity_id": "game", "market": market,
               "away_mean_runs": 4.1, "home_mean_runs": 4.6, **metadata}
    return game, quote, feature


@pytest.mark.parametrize("game_type", ["F", "D", "L", "W", "P"])
def test_postseason_game_type_blocks_before_model_input(game_type):
    game, quote, feature = _make(game_type=game_type)
    with pytest.raises(ValueError, match="POSTSEASON_LEGACY_SCORE_ENGINE_UNVALIDATED"):
        _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)


def test_bound_live_game_type_blocks_even_if_feature_omits_it():
    game, quote, feature = _make(bound_type="D")
    with pytest.raises(ValueError, match="POSTSEASON_LEGACY_SCORE_ENGINE_UNVALIDATED"):
        _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)


def test_explicit_postseason_rules_mode_blocks():
    game, quote, feature = _make(rules_mode="POSTSEASON")
    with pytest.raises(ValueError, match="POSTSEASON_LEGACY_SCORE_ENGINE_UNVALIDATED"):
        _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)


def test_false_regular_label_on_postseason_game_is_rejected():
    game, quote, feature = _make(game_type="D", rules_mode="REGULAR_SEASON")
    with pytest.raises(ValueError, match="MLB_GAME_RULES_MODE_CONFLICT"):
        _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)


@pytest.mark.parametrize("bad", ["?", "", "S", "E", True])
def test_unsupported_game_type_fails_closed(bad):
    game, quote, feature = _make(game_type=bad)
    with pytest.raises(ValueError, match="MLB_GAME_TYPE_INVALID"):
        _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)


def test_regular_season_keeps_frozen_engine_inputs_unchanged():
    game, quote, feature = _make(game_type="R", rules_mode="REGULAR_SEASON")
    with_metadata = _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)
    legacy_game, legacy_quote, legacy_feature = _make()
    legacy = _model_input(game=legacy_game, quote=legacy_quote, feature=legacy_feature, require_confirmed_lineup=True)
    assert with_metadata == legacy
    assert "rules_mode" not in with_metadata


def test_game_type_source_disagreement_is_blocked():
    game, quote, feature = _make(bound_type="R", game_type="D")
    with pytest.raises(ValueError, match="MLB_GAME_TYPE_SOURCE_CONFLICT"):
        _model_input(game=game, quote=quote, feature=feature, require_confirmed_lineup=True)
