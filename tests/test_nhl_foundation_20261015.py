"""Synthetic-fixture tests for the research-only NHL foundation (no real data)."""
import math
import random

import pytest

from sportsedge.research import nhl_foundation as nf
from sportsedge.research.nhl_foundation import (Goal, GamePath, NHLFoundationError,
                                                TeamInput)


def _team(tid, rate=3.0, en=3.0):
    pl = [f"{tid}_p{i}" for i in range(4)]
    return TeamInput(tid, rate, {p: 0.25 for p in pl}, {p: 1.0 for p in pl}, en)


H, A = _team("HOM"), _team("AWY")


def _paths(n=600, seed=7, **kw):
    rng = random.Random(seed)
    return [nf.simulate_game(H, A, rng, **kw) for _ in range(n)]


def test_conservation_every_path():
    for p in _paths():
        assert nf.check_path(p, H, A)
        for t in (H, A):
            assert p.team_goals(t.team_id) == sum(p.player_goals(x) for x in t.scorer_shares)
            assert p.team_goals(t.team_id) == sum(
                p.team_goals(t.team_id, periods=(k,)) for k in (1, 2, 3, 4))


def test_no_game_ends_tied_and_shootout_only_after_tied_ot():
    saw_so = saw_ot = False
    for p in _paths():
        h, a = p.final_score()
        assert h != a
        if p.shootout_winner:
            saw_so = True
            assert p.team_goals("HOM") == p.team_goals("AWY")
            assert not any(g.period == 4 for g in p.goals)
        if any(g.period == 4 for g in p.goals):
            saw_ot = True
    assert saw_so and saw_ot


def test_shootout_goal_counts_for_total_not_players():
    g = Goal("HOM", 1, 1.0, "HOM_p0", ())
    g2 = Goal("AWY", 2, 1.0, "AWY_p0", ())
    p = GamePath("HOM", "AWY", [g, g2], shootout_winner="HOM", teams=(H, A))
    assert nf.check_path(p, H, A)
    assert p.final_score() == (2, 1)
    assert nf.settle(p, "TOTAL", line=2.5) == "OVER"
    assert nf.settle(p, "MONEYLINE", selection="HOM") == "WIN"
    assert nf.settle(p, "REGULATION_3WAY", selection="DRAW") == "WIN"
    assert nf.settle(p, "PUCK_LINE", selection="HOM", line=-1.5) == "LOSE"
    assert nf.settle(p, "PUCK_LINE", selection="AWY", line=1.5) == "WIN"
    assert nf.settle(p, "GOES_TO_OT", selection="YES") == "WIN"
    assert sum(p.player_goals(x) for x in H.scorer_shares) == 1


def test_empty_net_only_in_p3_and_flagged():
    en = 0
    for p in _paths(1500, seed=3):
        for g in p.goals:
            if g.empty_net:
                en += 1
                assert g.period == 3 and g.minute >= nf.REG_PERIOD_MIN - 2.0
    assert en > 0


def test_assists_distinct_same_team_never_scorer():
    for p in _paths():
        for g in p.goals:
            assert g.scorer not in g.assists
            assert len(set(g.assists)) == len(g.assists) <= 2
            roster = (H if g.team_id == "HOM" else A).scorer_shares
            assert all(x in roster for x in g.assists)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True, "3"])
def test_nonfinite_or_bad_rate_refused(bad):
    with pytest.raises(NHLFoundationError):
        nf.simulate_game(TeamInput("HOM", bad, H.scorer_shares, H.assist_shares),
                         A, random.Random(1))


def test_unnormalized_shares_refused():
    t = TeamInput("HOM", 3.0, {"x": 0.5, "y": 0.4}, {})
    with pytest.raises(NHLFoundationError) as e:
        t.validate()
    assert e.value.code == "NHL_SCORER_SHARES_NOT_NORMALIZED"


def test_identity_collisions_refused():
    with pytest.raises(NHLFoundationError) as e:
        nf.simulate_game(H, _team("HOM"), random.Random(1))
    assert e.value.code == "NHL_TEAM_IDENTITY_COLLISION"
    clone = TeamInput("AWY", 3.0, H.scorer_shares, H.assist_shares)
    with pytest.raises(NHLFoundationError) as e:
        nf.simulate_game(H, clone, random.Random(1))
    assert e.value.code == "NHL_PLAYER_ON_BOTH_TEAMS"


@pytest.mark.parametrize("goals,sow,code", [
    ([Goal("HOM", 1, 1.0, "AWY_p0", ())], None, "NHL_SCORER_NOT_ON_TEAM"),
    ([Goal("HOM", 1, 1.0, "HOM_p0", ("HOM_p0",))], None, "NHL_ASSIST_INVALID"),
    ([Goal("HOM", 5, 1.0, "HOM_p0", ())], None, "NHL_PERIOD_INVALID"),
    ([Goal("HOM", 4, 6.0, "HOM_p0", ())], None, "NHL_GOAL_TIME_INVALID"),
    ([Goal("HOM", 1, float("nan"), "HOM_p0", ())], None, "NHL_GOAL_TIME_INVALID"),
    ([Goal("HOM", 4, 1.0, "HOM_p0", (), empty_net=True)], None, "NHL_EMPTY_NET_OUTSIDE_P3"),
    ([Goal("HOM", 1, 1.0, "HOM_p0", ())], "HOM", "NHL_SHOOTOUT_AFTER_DECIDED_GAME"),
    ([], None, "NHL_GAME_ENDED_TIED"),
    ([Goal("HOM", 1, 1.0, "HOM_p0", ()), Goal("HOM", 4, 1.0, "HOM_p1", ())],
     None, "NHL_OT_AFTER_DECIDED_REGULATION"),
    ([Goal("HOM", 4, 1.0, "HOM_p0", ()), Goal("AWY", 4, 2.0, "AWY_p1", ())],
     None, "NHL_OT_NOT_SUDDEN_DEATH"),
    ([Goal("XXX", 1, 1.0, "HOM_p0", ())], None, "NHL_GOAL_UNKNOWN_TEAM"),
])
def test_impossible_paths_refused(goals, sow, code):
    with pytest.raises(NHLFoundationError) as e:
        nf.check_path(GamePath("HOM", "AWY", goals, sow), H, A)
    assert e.value.code == code


def test_settlement_identity_and_line_refusals():
    p = _paths(1)[0]
    with pytest.raises(NHLFoundationError):
        nf.settle(p, "MONEYLINE", selection="NYR")
    for bad in (float("nan"), float("inf"), None, True):
        with pytest.raises(NHLFoundationError):
            nf.settle(p, "TOTAL", line=bad)
    with pytest.raises(NHLFoundationError):
        nf.settle(p, "PERIOD_TOTAL", period=4, line=0.5)
    with pytest.raises(NHLFoundationError) as e:
        nf.settle(p, "FIRST_GOAL_SCORER")
    assert e.value.code == "NHL_MARKET_NO_SETTLEMENT"
    with pytest.raises(NHLFoundationError) as e:
        nf.settle_player_prop(p, H, A, "PLAYER_GOALS", "AWY_p0", 0.5, "HOM")
    assert e.value.code == "NHL_PLAYER_IDENTITY_MISMATCH"
    with pytest.raises(NHLFoundationError):
        nf.settle_player_prop(p, H, A, "PLAYER_GOALS", "HOM_p0", 0.5, "NYR")


def test_whole_line_push():
    p = GamePath("HOM", "AWY", [Goal("HOM", 1, 1.0, "HOM_p0", ()),
                                Goal("HOM", 2, 1.0, "HOM_p1", ()),
                                Goal("AWY", 3, 1.0, "AWY_p1", ())], teams=(H, A))
    assert nf.settle(p, "TOTAL", line=3) == "PUSH"
    assert nf.settle(p, "PUCK_LINE", selection="AWY", line=1) == "PUSH"


def test_deterministic_given_seed():
    a = [x.final_score() for x in _paths(50, seed=11)]
    b = [x.final_score() for x in _paths(50, seed=11)]
    assert a == b


def test_playoff_mode_refuses_rather_than_inventing_shootout():
    with pytest.raises(NHLFoundationError) as e:
        for _ in range(2000):
            nf.simulate_game(_team("HOM", 0.0), _team("AWY", 0.0), random.Random(1),
                             allow_shootout=False)
    assert e.value.code == "NHL_PLAYOFF_OT_NOT_MODELED"


def test_terminal_map_one_terminal_never_validated():
    for m in nf.MARKET_TERMINALS:
        r = nf.market_terminal(m)
        assert r["terminal"] in nf.TERMINALS
        assert r["terminal"] not in ("VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD")
        assert r["probability"] is None and r["price"] is None and r["ev"] is None
        assert r["validation"] == "NO_VALIDATION"
    assert nf.market_terminal("MADE_UP")["terminal"] == "NO_ENGINE"
    assert nf.STATUS == "RESEARCH_ONLY"


def test_every_research_only_market_has_settlement():
    from sportsedge.research import nhl_foundation_props as npp
    p = _paths(1)[0]
    kw = {"selection": "HOM", "line": 0.5, "period": 1, "player_id": "HOM_p0"}
    hp = npp.TeamPropsInput("HOM", "HOM_g", {}, {}, {}, 0.2)
    ap = npp.TeamPropsInput("AWY", "AWY_g", {}, {}, {}, 0.2)
    props = npp.simulate_props(p, H, A, hp, ap, random.Random(0))
    for m, (t, _) in nf.MARKET_TERMINALS.items():
        if t != "RESEARCH_ONLY":
            continue
        if m in npp.PROPS_MARKETS:   # settled by the props layer, not the game layer
            pid = "HOM_g" if m == "GOALIE_SAVES" else "HOM_p0"
            assert npp.settle_prop(props, H, A, m, player_id=pid, team_id="HOM",
                                   line=0.5) in ("OVER", "UNDER", "PUSH")
            with pytest.raises(NHLFoundationError):
                nf.settle(p, m, **kw)
            continue
        k = dict(kw)
        if m == "REGULATION_3WAY":
            k["selection"] = "DRAW"
        if m in ("GOES_TO_OT", "EMPTY_NET_GOAL"):
            k["selection"] = "YES"
        assert nf.settle(p, m, **k) in ("WIN", "LOSE", "PUSH", "OVER", "UNDER")
