"""RED (t211u, #2358): Ask Sims answers only when score paths are bound to
the asked game's team identities; unbound or swapped paths refuse."""
import pytest

from sportsedge.sports.nfl.ask_sims import (
    AskSimsError, ask_score_paths, ask_unified_score_sims)

HOME, AWAY = "DEN", "SEA"
RAW = [{"home_score": 10, "away_score": 17}, {"home_score": 35, "away_score": 10}]


def _bound(home=HOME, away=AWAY):
    return [dict(p, home_team=home, away_team=away) for p in RAW]


def test_unbound_paths_refused():
    with pytest.raises(AskSimsError, match="ASK_SIMS_PATH_IDENTITY_UNBOUND"):
        ask_score_paths(RAW, "SEA wins", home_team=HOME, away_team=AWAY)


def test_swapped_paths_refused():
    with pytest.raises(AskSimsError, match="ASK_SIMS_PATH_IDENTITY_MISMATCH"):
        ask_score_paths(_bound(AWAY, HOME), "SEA wins", home_team=HOME, away_team=AWAY)


def test_other_game_paths_refused():
    with pytest.raises(AskSimsError, match="ASK_SIMS_PATH_IDENTITY_MISMATCH"):
        ask_score_paths(_bound("KC", "LV"), "SEA wins", home_team=HOME, away_team=AWAY)


def test_mixed_identity_paths_refused():
    paths = _bound() + [dict(RAW[0], home_team=AWAY, away_team=HOME)]
    with pytest.raises(AskSimsError, match="ASK_SIMS_PATH_IDENTITY_MISMATCH"):
        ask_score_paths(paths, "SEA wins", home_team=HOME, away_team=AWAY)


def test_bound_paths_answer():
    row = ask_score_paths(_bound(), "SEA wins", home_team=HOME, away_team=AWAY)
    assert row["win_count"] == 1 and row["sample_count"] == 2


def test_engine_without_declared_teams_refused():
    from sportsedge.sports.nfl.unified_market_engine import run_unified_nfl_model
    engine = run_unified_nfl_model(game_id="2026_06_SEA_DEN", home_team=HOME,
                                   away_team=AWAY, attempt9_margin=0.0,
                                   attempt9_total=44.0, n_sims=64, seed=7)
    for key in ("home_team", "away_team"):
        e = dict(engine)
        e.pop(key)
        with pytest.raises(AskSimsError, match="ASK_SIMS_GAME_IDENTITY_UNBOUND"):
            ask_unified_score_sims(e, "SEA wins", home_team=HOME, away_team=AWAY)
    with pytest.raises(AskSimsError, match="ASK_SIMS_GAME_IDENTITY_MISMATCH"):
        ask_unified_score_sims(engine, "SEA wins", home_team=AWAY, away_team=HOME)
