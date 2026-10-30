"""Synthetic-fixture tests for the research-only CBB props layer (no real data)."""
import random

import pytest

from sportsedge.research import cbb_foundation as F
from sportsedge.research import cbb_foundation_props as P
from sportsedge.research.cbb_foundation import Event, FoundationError, GamePath, PlayerInput, TeamInput
from sportsedge.research.cbb_foundation_props import PlayerPropsInput, TeamPropsInput

S = F.SPORT


def _team(tid):
    return TeamInput(tid, tuple(PlayerInput(f"{tid}_p{i}", 8.0, 2.5, 4.0) for i in range(5)),
                     espn_id={"HOM": "SYN-0001", "AWY": "SYN-0002"}[tid])


H, A = _team("HOM"), _team("AWY")
PP = PlayerPropsInput(miss_fg2_per40=8.0, miss_fg3_per40=4.0, miss_ft_per40=1.5,
                      tov_per40=3.0)


def _pin(t, **kw):
    return TeamPropsInput(t.team_id, {p: PP for p in t.roster}, **kw)


HP, AP = _pin(H), _pin(A)


def _paths(n=150, seed=21):
    rng = random.Random(seed)
    return [P.simulate_props(F.simulate_game(H, A, rng), H, A, HP, AP, rng) for _ in range(n)]


def test_rebounds_reconcile_with_live_misses():
    for p in _paths():
        assert P.check_props(p)
        for t, o in (("HOM", "AWY"), ("AWY", "HOM")):
            oreb = sum(1 for r in p.rebounds if r[0] == t and r[1] == t)
            dreb = sum(1 for r in p.rebounds if r[0] == t and r[1] == o)
            assert oreb + dreb == p.live_misses[t]
            missed = sum(n for (pid, _), n in p.misses.items() if pid in p.rosters[t])
            assert p.live_misses[t] <= missed
        player_reb = sum(p.stat(x, "REB") for r in p.rosters.values() for x in r)
        team_reb = sum(1 for r in p.rebounds if r[2] == "TEAM")
        assert player_reb + team_reb == sum(p.live_misses.values())


def test_assists_only_on_teammate_made_fg():
    for p in _paths():
        made_fg = sum(1 for e in p.game.events if e.kind in ("FG2", "FG3"))
        assert len(p.assists) <= made_fg
        for i, a in p.assists:
            e = p.game.events[i]
            assert e.kind != "FT" and a != e.player_id and a in p.rosters[e.team_id]


def test_steals_and_blocks_bounded_by_opponent_events():
    for p in _paths():
        for t, o in (("HOM", "AWY"), ("AWY", "HOM")):
            stl = sum(p.stat(x, "STL") for x in p.rosters[t])
            tov = sum(p.stat(x, "TOV") for x in p.rosters[o])
            assert stl <= tov
            blk = sum(p.stat(x, "BLK") for x in p.rosters[t])
            fgm = sum(n for (pid, k), n in p.misses.items() if pid in p.rosters[o] and k != "FT")
            assert blk <= fgm


def test_combos_and_double_double_consistent():
    for p in _paths(60):
        for t, r in p.rosters.items():
            for x in r:
                pts, reb, ast = (p.stat(x, c) for c in ("PTS", "REB", "AST"))
                v = pts + reb + ast
                assert P.settle_prop(p, "PLAYER_PRA", player_id=x, team_id=t, line=v) == "PUSH"
                assert P.settle_prop(p, "PLAYER_PR", player_id=x, team_id=t, line=pts + reb) == "PUSH"
                assert P.settle_prop(p, "PLAYER_PA", player_id=x, team_id=t, line=pts + ast) == "PUSH"
                assert P.settle_prop(p, "PLAYER_RA", player_id=x, team_id=t, line=reb + ast) == "PUSH"
                dd = sum(1 for c in P.CATEGORIES if p.stat(x, c) >= 10) >= 2
                assert P.settle_prop(p, "DOUBLE_DOUBLE", player_id=x, team_id=t,
                                     selection="YES") == ("WIN" if dd else "LOSE")


def test_race_winner_coherent_with_timeline():
    for p in _paths(80):
        h, a = p.game.final_score()
        for n in (10, 20, max(h, a), max(h, a) + 1):
            w = P.race_winner(p, n)
            if n > max(h, a):
                assert w is None
                assert P.settle_prop(p, "RACE_TO_POINTS", selection="HOM", n=n) == "VOID"
            else:
                assert w is not None and p.game.points(w) >= n
                assert P.settle_prop(p, "RACE_TO_POINTS", selection=w, n=n) == "WIN"


def _fixed():
    g = GamePath("HOM", "AWY", [Event("HOM", "HOM_p0", 1, "FG2"),
                                Event("HOM", "HOM_p1", 1, "FT"),
                                Event("AWY", "AWY_p0", 2, "FG3")])
    zero = PlayerPropsInput(miss_fg2_per40=6.0)
    pin = lambda t: TeamPropsInput(t.team_id, {x: zero for x in t.roster}, assist_rate=0.0)
    return P.simulate_props(g, H, A, pin(H), pin(A), random.Random(3))


@pytest.mark.parametrize("mutate,code", [
    (lambda p: p.rebounds.append(("HOM", "HOM", "HOM_p0")), "REBOUNDS_NOT_CONSERVED"),
    (lambda p: p.assists.append((1, "HOM_p0")), "ASSIST_ON_NON_FG"),
    (lambda p: p.assists.append((0, "HOM_p0")), "ASSIST_NOT_BY_TEAMMATE"),
    (lambda p: p.assists.append((2, "HOM_p0")), "ASSIST_NOT_BY_TEAMMATE"),
    (lambda p: p.assists.extend([(0, "HOM_p1"), (0, "HOM_p2")]), "ASSIST_EVENT_INVALID"),
    (lambda p: p.assists.append((99, "HOM_p1")), "ASSIST_EVENT_INVALID"),
    (lambda p: p.steals.append(("HOM_p0", "HOM_p1")), "STEAL_IDENTITY_INVALID"),
    (lambda p: p.steals.extend([("HOM_p4", "AWY_p0")] * 50), "STEALS_EXCEED_TURNOVERS"),
    (lambda p: p.blocks.append(("HOM_p0", "HOM_p1")), "BLOCK_IDENTITY_INVALID"),
    (lambda p: p.blocks.extend([("HOM_p3", "AWY_p0")] * 99), "BLOCKS_EXCEED_MISSES"),
    (lambda p: p.misses.__setitem__(("HOM_p0", "FG2"), -1), "MISS_COUNT_INVALID"),
    (lambda p: p.misses.__setitem__(("ZZZ", "FG2"), 1), "MISS_IDENTITY_INVALID"),
    (lambda p: p.live_misses.__setitem__("HOM", 10 ** 6), "LIVE_MISSES_INVALID"),
    (lambda p: p.turnovers.__setitem__("HOM_p0", float("nan")), "TURNOVER_INVALID"),
    (lambda p: p.timeline.pop(), "TIMELINE_INVALID"),
    (lambda p: p.timeline.reverse(), "TIMELINE_PERIOD_ORDER"),
])
def test_tampered_props_refused(mutate, code):
    p = _fixed()
    assert P.check_props(p)
    mutate(p)
    with pytest.raises(FoundationError) as e:
        P.check_props(p)
    assert e.value.code == f"{S}_{code}"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True])
def test_nonfinite_inputs_refused(bad):
    g = F.simulate_game(H, A, random.Random(1))
    with pytest.raises(FoundationError):
        P.simulate_props(g, H, A, TeamPropsInput("HOM", {x: PlayerPropsInput(tov_per40=bad)
                                                         for x in H.roster}), AP, random.Random(1))
    with pytest.raises(FoundationError):
        P.simulate_props(g, H, A, _pin(H, assist_rate=bad), AP, random.Random(1))


def test_identity_refusals():
    g = F.simulate_game(H, A, random.Random(1))
    with pytest.raises(FoundationError) as e:
        P.simulate_props(g, H, A, AP, HP, random.Random(1))
    assert e.value.code == f"{S}_PROPS_TEAM_IDENTITY_MISMATCH"
    short = TeamPropsInput("HOM", {"HOM_p0": PP})
    with pytest.raises(FoundationError) as e:
        P.simulate_props(g, H, A, short, AP, random.Random(1))
    assert e.value.code == f"{S}_PROPS_ROSTER_MISMATCH"
    with pytest.raises(FoundationError):
        P.simulate_props(g, H, A, _pin(H, oreb_rate=1.2), AP, random.Random(1))
    p = P.simulate_props(g, H, A, HP, AP, random.Random(1))
    with pytest.raises(FoundationError) as e:
        P.settle_prop(p, "PLAYER_REBOUNDS", player_id="AWY_p0", team_id="HOM", line=4.5)
    assert e.value.code == f"{S}_PLAYER_IDENTITY_MISMATCH"
    with pytest.raises(FoundationError):
        P.settle_prop(p, "PLAYER_REBOUNDS", player_id="HOM_p0", team_id="ZZZ", line=4.5)
    with pytest.raises(FoundationError):
        P.settle_prop(p, "RACE_TO_POINTS", selection="ZZZ", n=10)
    for bad_n in (0, -5, 2.5, True, None):
        with pytest.raises(FoundationError):
            P.settle_prop(p, "RACE_TO_POINTS", selection="HOM", n=bad_n)
    for ln in (float("nan"), float("inf"), None):
        with pytest.raises(FoundationError):
            P.settle_prop(p, "PLAYER_PRA", player_id="HOM_p0", team_id="HOM", line=ln)
    with pytest.raises(FoundationError) as e:
        P.settle_prop(p, "FIRST_BASKET", player_id="HOM_p0", team_id="HOM", line=0.5)
    assert e.value.code == f"{S}_MARKET_NO_SETTLEMENT"


def test_status_and_map():
    assert P.STATUS == "RESEARCH_ONLY" and P.VALIDATION == "NO_VALIDATION"
    for m in ("PLAYER_REBOUNDS", "PLAYER_ASSISTS", "PLAYER_PRA", "PLAYER_TURNOVERS",
              "PLAYER_STEALS_BLOCKS", "DOUBLE_DOUBLE", "RACE_TO_POINTS"):
        r = F.market_terminal(m)
        assert r["terminal"] == "RESEARCH_ONLY" and r["probability"] is None and r["price"] is None


def test_illinois_team_refused_by_props_layer():
    il = TeamInput("Bradley", H.players)
    g = GamePath("Bradley", "AWY", [Event("Bradley", "HOM_p0", 1, "FG2")])
    with pytest.raises(FoundationError) as e:
        P.simulate_props(g, il, A, TeamPropsInput("Bradley", {x: PP for x in H.roster}), AP,
                         random.Random(1))
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
