import pytest

from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.mlb_joint_mode_bridge import (
    MLBJointModeBridgeError,
    _content_sha,
    _live_game_state,
)


def _lineup(team_id: int, side: str, start: int, *, confirmed: bool = True) -> TeamLineup:
    return TeamLineup(
        team_id=team_id,
        side=side,
        player_ids=tuple(range(start, start + 9)),
        batting_slots=tuple(range(1, 10)),
        confirmed=confirmed,
    )


def _game(**overrides) -> LiveGame:
    values = {
        "game_pk": 777001,
        "away_team_id": 10,
        "home_team_id": 20,
        "away_probable_pitcher_id": 101,
        "home_probable_pitcher_id": 202,
        "away_lineup": _lineup(10, "away", 1001),
        "home_lineup": _lineup(20, "home", 2001),
        "venue_id": 55,
        "official_date": "2026-09-12",
        "game_number": 1,
        "double_header": "N",
        "status": "Scheduled",
    }
    values.update(overrides)
    return LiveGame(**values)


def _state_hash(game: LiveGame) -> str:
    return _content_sha(_live_game_state(game))


def test_game_state_binding_requires_both_probable_starters():
    with pytest.raises(MLBJointModeBridgeError, match="both probable pitchers required"):
        _live_game_state(_game(home_probable_pitcher_id=None))


def test_game_state_binding_requires_confirmed_lineups():
    with pytest.raises(MLBJointModeBridgeError, match="confirmed MLB batting orders required"):
        _live_game_state(_game(away_lineup=_lineup(10, "away", 1001, confirmed=False)))


def test_game_state_binding_changes_when_starter_changes():
    assert _state_hash(_game()) != _state_hash(_game(home_probable_pitcher_id=203))


def test_game_state_binding_changes_when_batting_order_changes():
    original = _game()
    swapped = TeamLineup(
        team_id=10,
        side="away",
        player_ids=original.away_lineup.player_ids,
        batting_slots=(2, 1, 3, 4, 5, 6, 7, 8, 9),
        confirmed=True,
    )
    assert _state_hash(original) != _state_hash(_game(away_lineup=swapped))
