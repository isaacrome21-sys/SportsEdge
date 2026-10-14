"""Direct wiring tests: MLB public batter history enforces source identity.

Offline mocked StatsAPI fixtures only (reused from the phone-history tests);
no network, no odds-derived probabilities.
"""
import copy

import pytest

from sportsedge.mlb_public_batter_history import MLBBatterPublicSource, MissingMLBBatterHistory
from tests.test_mlb_batter_public_phone_history import ID, KICKOFF, NOW, mock_public


def _getter(mutate=None, past_games=12):
    base = mock_public(past_games=past_games)

    def get(url):
        data = base(url)
        if mutate is not None and "/people/" in url and "/stats" in url:
            data = copy.deepcopy(data)
            mutate(data["stats"][0]["splits"])
        return data
    return get


def _prior(mutate=None, past_games=12):
    return MLBBatterPublicSource(getter=_getter(mutate, past_games)).prior_games(
        away="Los Angeles Dodgers", home="Milwaukee Brewers", player_name="Mookie Betts",
        owner_kickoff=KICKOFF, as_of=NOW.isoformat())


def test_matching_player_ids_accepted():
    def m(splits):
        for s in splits:
            s["player"] = {"id": int(ID)}
    out = _prior(m)
    assert out["batter_id"] == ID and out["prior_game_count"] == 12


def test_wrong_player_row_rejects_whole_response():
    def m(splits):
        splits[3]["player"] = {"id": 999999}
    with pytest.raises(MissingMLBBatterHistory, match="SOURCE_IDENTITY_SPLIT_PLAYER_ID_MISMATCH"):
        _prior(m)


def test_malformed_player_identity_rejected():
    def m(splits):
        splits[0]["player"] = "Mookie Betts"
    with pytest.raises(MissingMLBBatterHistory, match="SOURCE_IDENTITY_SPLIT_PLAYER_IDENTITY_MALFORMED"):
        _prior(m)


def test_conflicting_duplicate_game_refused():
    def m(splits):
        dup = copy.deepcopy(splits[4])
        dup["stat"]["hits"] = dup["stat"]["hits"] + 2
        splits.append(dup)
    with pytest.raises(MissingMLBBatterHistory, match="SOURCE_IDENTITY_GAME_PK_DUPLICATE_CONFLICTING_STATS"):
        _prior(m)


def test_exact_duplicate_game_collapsed():
    def m(splits):
        splits.append(copy.deepcopy(splits[4]))
        splits.append(copy.deepcopy(splits[7]))
    out = _prior(m)
    assert out["prior_game_count"] == 12
    assert out["prior_plate_appearances"] == 12 * 4
