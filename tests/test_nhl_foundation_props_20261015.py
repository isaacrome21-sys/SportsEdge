"""Synthetic-fixture tests for the research-only NHL props layer (no real data)."""
import random

import pytest

from sportsedge.research import nhl_foundation as nf
from sportsedge.research import nhl_foundation_props as npp
from sportsedge.research.nhl_foundation import Goal, GamePath, NHLFoundationError, TeamInput
from sportsedge.research.nhl_foundation_props import PropsPath, TeamPropsInput


def _team(tid):
    pl = [f"{tid}_p{i}" for i in range(4)]
    return TeamInput(tid, 3.0, {p: 0.25 for p in pl}, {p: 1.0 for p in pl}, 3.0)


H, A = _team("HOM"), _team("AWY")


def _pin(t, sog=6.0, blk=1.0, hit=1.5, pp=0.2, goalie=None):
    r = t.scorer_shares
    return TeamPropsInput(t.team_id, goalie or f"{t.team_id}_g", {p: sog for p in r},
                          {p: blk for p in r}, {p: hit for p in r}, pp)


HP, AP = _pin(H), _pin(A)


def _paths(n=400, seed=13):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        g = nf.simulate_game(H, A, rng)
        out.append(npp.simulate_props(g, H, A, HP, AP, rng))
    return out


def test_goals_subset_of_shots_and_team_sums():
    for p in _paths():
        assert npp.check_props(p, H, A)
        for t in (H, A):
            for pid in t.scorer_shares:
                assert p.sog[pid] >= p.game.player_goals(pid)
            assert p.team_sog(t.team_id, t.scorer_shares) >= p.game.team_goals(t.team_id)


def test_saves_equal_opponent_sog_minus_goals():
    rost = {"HOM": set(H.scorer_shares), "AWY": set(A.scorer_shares)}
    for p in _paths():
        for team, opp in (("HOM", "AWY"), ("AWY", "HOM")):
            s = npp.goalie_saves(p, rost, team)
            assert s == p.team_sog(opp, rost[opp]) - p.game.team_goals(opp) >= 0


def test_shootout_never_adds_shots():
    g = GamePath("HOM", "AWY", [Goal("HOM", 1, 1.0, "HOM_p0", ()),
                                Goal("AWY", 2, 1.0, "AWY_p0", ())], shootout_winner="AWY")
    p = npp.simulate_props(g, H, A, _pin(H, sog=0), _pin(A, sog=0), random.Random(1))
    assert p.sog["HOM_p0"] == 1 and p.sog["AWY_p0"] == 1
    assert sum(p.sog.values()) == 2      # SO decisive goal is not a shot


def test_pp_points_tied_to_pp_goals():
    for p in _paths():
        for t in (H, A):
            team_pp = [i for i in p.pp_goal_index if p.game.goals[i].team_id == t.team_id]
            assert len(team_pp) <= p.game.team_goals(t.team_id)
            expect = sum(1 + len(p.game.goals[i].assists) for i in team_pp)
            assert sum(npp.pp_points(p, x) for x in t.scorer_shares) == expect
        for i in p.pp_goal_index:
            assert not p.game.goals[i].empty_net


def test_zero_pp_share_means_zero_pp_points():
    for p in [npp.simulate_props(nf.simulate_game(H, A, random.Random(s)), H, A,
                                 _pin(H, pp=0.0), _pin(A, pp=0.0), random.Random(s))
              for s in range(50)]:
        assert not p.pp_goal_index


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True])
def test_nonfinite_props_inputs_refused(bad):
    g = nf.simulate_game(H, A, random.Random(1))
    for pin in (_pin(H, sog=bad), _pin(H, blk=bad), _pin(H, hit=bad), _pin(H, pp=bad)):
        with pytest.raises(NHLFoundationError):
            npp.simulate_props(g, H, A, pin, AP, random.Random(1))


def test_identity_refusals():
    g = nf.simulate_game(H, A, random.Random(1))
    with pytest.raises(NHLFoundationError) as e:
        npp.simulate_props(g, H, A, AP, HP, random.Random(1))
    assert e.value.code == "NHL_PROPS_TEAM_IDENTITY_MISMATCH"
    with pytest.raises(NHLFoundationError) as e:
        npp.simulate_props(g, H, A, _pin(H, goalie="X"), _pin(A, goalie="X"), random.Random(1))
    assert e.value.code == "NHL_GOALIE_IDENTITY_COLLISION"
    with pytest.raises(NHLFoundationError) as e:
        npp.simulate_props(g, H, A, _pin(H, goalie="HOM_p0"), AP, random.Random(1))
    assert e.value.code == "NHL_GOALIE_IS_SKATER"
    bad = TeamPropsInput("HOM", "HOM_g", {"AWY_p0": 1.0}, {}, {}, 0.1)
    with pytest.raises(NHLFoundationError) as e:
        npp.simulate_props(g, H, A, bad, AP, random.Random(1))
    assert e.value.code == "NHL_PROPS_PLAYER_NOT_ON_ROSTER"
    with pytest.raises(NHLFoundationError):
        npp.simulate_props(g, H, A, _pin(H, pp=1.5), AP, random.Random(1))
    p = npp.simulate_props(g, H, A, HP, AP, random.Random(1))
    with pytest.raises(NHLFoundationError) as e:
        npp.settle_prop(p, H, A, "GOALIE_SAVES", player_id="AWY_g", team_id="HOM", line=20.5)
    assert e.value.code == "NHL_GOALIE_IDENTITY_MISMATCH"
    with pytest.raises(NHLFoundationError) as e:
        npp.settle_prop(p, H, A, "PLAYER_SHOTS", player_id="AWY_p0", team_id="HOM", line=2.5)
    assert e.value.code == "NHL_PLAYER_IDENTITY_MISMATCH"
    with pytest.raises(NHLFoundationError):
        npp.settle_prop(p, H, A, "PLAYER_SHOTS", player_id="HOM_p0", team_id="NYR", line=2.5)
    for ln in (float("nan"), float("inf"), None):
        with pytest.raises(NHLFoundationError):
            npp.settle_prop(p, H, A, "PLAYER_SHOTS", player_id="HOM_p0", team_id="HOM", line=ln)
    with pytest.raises(NHLFoundationError) as e:
        npp.settle_prop(p, H, A, "PLAYER_PIM", player_id="HOM_p0", team_id="HOM", line=0.5)
    assert e.value.code == "NHL_MARKET_NO_SETTLEMENT"


@pytest.mark.parametrize("mutate,code", [
    (lambda p: p.sog.__setitem__("HOM_p0", -1), "NHL_SOG_INVALID"),
    (lambda p: p.sog.__setitem__("HOM_p0", 1.5), "NHL_SOG_INVALID"),
    (lambda p: p.blocks.__setitem__("HOM_p1", True), "NHL_BLOCKS_INVALID"),
    (lambda p: p.sog.pop("AWY_p2"), "NHL_SOG_MISSING_PLAYER"),
    (lambda p: setattr(p, "pp_goal_index", frozenset({99})), "NHL_PP_GOAL_UNKNOWN"),
])
def test_tampered_props_refused(mutate, code):
    g = GamePath("HOM", "AWY", [Goal("HOM", 1, 1.0, "HOM_p0", ())])
    p = npp.simulate_props(g, H, A, HP, AP, random.Random(2))
    mutate(p)
    with pytest.raises(NHLFoundationError) as e:
        npp.check_props(p, H, A)
    assert e.value.code == code


def test_goal_without_shot_refused():
    g = GamePath("HOM", "AWY", [Goal("HOM", 1, 1.0, "HOM_p0", ()),
                                Goal("HOM", 2, 1.0, "HOM_p0", ())])
    p = PropsPath(g, {"HOM": "HOM_g", "AWY": "AWY_g"},
                  {x: 0 for x in list(H.scorer_shares) + list(A.scorer_shares)} | {"HOM_p0": 1},
                  {}, {}, frozenset())
    with pytest.raises(NHLFoundationError) as e:
        npp.check_props(p, H, A)
    assert e.value.code == "NHL_GOALS_EXCEED_SOG"


def test_status_and_map():
    assert npp.STATUS == "RESEARCH_ONLY" and npp.VALIDATION == "NO_VALIDATION"
    for m in npp.PROPS_MARKETS:
        r = nf.market_terminal(m)
        assert r["terminal"] == "RESEARCH_ONLY" and r["probability"] is None
