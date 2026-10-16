"""RED (t212): Ask Sims replay goes through the V2 guarded grid + sampler.
A malformed grid is refused and never reaches the V1 sampler; team binding
is kept."""
import pytest

from sportsedge.sports.nfl import discrete_v2
from sportsedge.sports.nfl import unified_market_engine as v1
from sportsedge.sports.nfl import unified_market_engine_v2 as v2
from sportsedge.sports.nfl.ask_sims import AskSimsError, ask_unified_score_sims

HOME, AWAY = "DEN", "SEA"


def _engine():
    return v1.run_unified_nfl_model(game_id="2026_06_SEA_DEN", home_team=HOME,
                                    away_team=AWAY, attempt9_margin=0.0,
                                    attempt9_total=44.0, n_sims=64, seed=7)


BAD = {
    "short_mass": [[0.2, 0.2], [0.2, 0.2]],
    "nan": [[0.5, float("nan")], [0.25, 0.25]],
    "negative": [[0.75, -0.25], [0.25, 0.25]],
    "over_mass": [[0.5, 0.5], [0.5, 0.5]],
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_malformed_grid_refused_and_never_reaches_v1(monkeypatch, name):
    engine = _engine()
    bad = BAD[name]
    monkeypatch.setattr(discrete_v2, "score_grid", lambda *a, **k: bad)
    monkeypatch.setattr(v2, "score_grid", lambda *a, **k: bad)
    calls = []
    monkeypatch.setattr(v1, "sample_score_paths", lambda *a, **k: calls.append(a) or [])
    with pytest.raises((AskSimsError, v2.UnifiedNflV2GridError)) as exc:
        ask_unified_score_sims(engine, "SEA wins", home_team=HOME, away_team=AWAY)
    assert "SCORE_GRID_" in str(exc.value)
    assert calls == []


def test_valid_replay_still_answers_and_stays_team_bound():
    engine = _engine()
    out = ask_unified_score_sims(engine, "SEA wins", home_team=HOME, away_team=AWAY)
    assert out["sample_count"] == 64
    with pytest.raises(AskSimsError, match="ASK_SIMS_GAME_IDENTITY_MISMATCH"):
        ask_unified_score_sims(engine, "SEA wins", home_team=AWAY, away_team=HOME)


def test_ask_sims_imports_no_v1_sampler():
    import ast, inspect
    from sportsedge.sports.nfl import ask_sims
    tree = ast.parse(inspect.getsource(ask_sims))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("unified_market_engine"):
            assert not {a.name for a in node.names} & {"sample_score_paths", "price_game_market"}
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("discrete_v2"):
            assert "score_grid" not in {a.name for a in node.names}
