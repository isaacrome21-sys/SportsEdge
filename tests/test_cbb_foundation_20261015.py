"""Synthetic-fixture tests for the research-only CBB foundation (no real data)."""
import random

import pytest

from sportsedge.research import cbb_foundation as F
from sportsedge.research.cbb_foundation import Event, FoundationError, GamePath, PlayerInput, TeamInput

S = F.SPORT
REG = tuple(range(1, F.REG_PERIODS + 1))


def _team(tid, scale=1.0):
    return TeamInput(tid, tuple(PlayerInput(f"{tid}_p{i}", 8 * scale, 2.5 * scale, 4 * scale)
                                for i in range(5)))


H, A = _team("HOM"), _team("AWY")


def _paths(n=400, seed=5):
    rng = random.Random(seed)
    return [F.simulate_game(H, A, rng) for _ in range(n)]


def test_conservation_every_path():
    for p in _paths():
        assert F.check_path(p, H, A)
        for t in (H, A):
            tot = p.points(t.team_id)
            assert tot == sum(p.player_points(x) for x in t.roster)
            assert tot == sum(p.points(t.team_id, (k,)) for k in range(1, p.periods_played + 1))
            for x in t.roster:
                assert p.player_points(x) == (2 * p.player_count(x, "FG2")
                                              + 3 * p.player_count(x, "FG3")
                                              + p.player_count(x, "FT"))


def test_never_tied_and_ot_only_when_regulation_tied():
    saw_ot = False
    for p in _paths(2000, seed=9):
        h, a = p.final_score()
        assert h != a
        if p.periods_played > F.REG_PERIODS:
            saw_ot = True
            assert p.points("HOM", REG) == p.points("AWY", REG)
    assert saw_ot


def _ot_path():
    for p in _paths(3000, seed=2):
        if p.periods_played > F.REG_PERIODS:
            return p
    raise AssertionError("no OT path in fixture")


def test_ot_settlement_scopes():
    p = _ot_path()
    # Regulation-only segment ties -> 2-way segment ML pushes; full game never pushes.
    last_reg = "Q4" if F.REG_PERIODS == 4 else "2H_REG"
    assert F.settle(p, "MONEYLINE", selection="HOM") in ("WIN", "LOSE")
    assert F.settle(p, "GOES_TO_OT", selection="YES") == "WIN"
    h, a = p.final_score()
    assert F.settle(p, "TOTAL", line=h + a - 0.5) == "OVER"   # OT points count
    second = F.settle(p, "TOTAL", segment="2H", line=0)
    assert second in ("OVER", "PUSH")
    sec_pts = sum(p.points(t, tuple(range(F.REG_PERIODS // 2 + 1, p.periods_played + 1)))
                  for t in ("HOM", "AWY"))
    assert F.settle(p, "TOTAL", segment="2H", line=sec_pts) == "PUSH"
    first = F.REG_PERIODS // 2
    fh = sum(p.points(t, tuple(range(1, first + 1))) for t in ("HOM", "AWY"))
    assert F.settle(p, "TOTAL", segment="1H", line=fh) == "PUSH"
    del last_reg


def test_whole_number_push_and_spread():
    p = GamePath("HOM", "AWY", [Event("HOM", "HOM_p0", 1, "FG3"), Event("AWY", "AWY_p0", 2, "FG2")])
    assert F.check_path(p, H, A)
    assert F.settle(p, "SPREAD", selection="HOM", line=-1) == "PUSH"
    assert F.settle(p, "SPREAD", selection="AWY", line=1.5) == "WIN"
    assert F.settle(p, "TOTAL", line=5) == "PUSH"
    assert F.settle(p, "TEAM_TOTAL", selection="HOM", line=2.5) == "OVER"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, True, None])
def test_nonfinite_rates_refused(bad):
    t = TeamInput("HOM", (PlayerInput("HOM_p0", bad, 1.0, 1.0),))
    with pytest.raises(FoundationError) as e:
        F.simulate_game(t, A, random.Random(1))
    assert e.value.code.startswith(S + "_INPUT_")


@pytest.mark.parametrize("bad", [float("nan"), float("-inf"), None, True, "5"])
def test_nonfinite_lines_refused(bad):
    p = _paths(1)[0]
    for m, kw in (("TOTAL", {}), ("SPREAD", {"selection": "HOM"}),
                  ("TEAM_TOTAL", {"selection": "HOM"})):
        with pytest.raises(FoundationError):
            F.settle(p, m, line=bad, **kw)


def test_identity_refusals():
    with pytest.raises(FoundationError) as e:
        F.simulate_game(H, _team("HOM"), random.Random(1))
    assert e.value.code == f"{S}_TEAM_IDENTITY_COLLISION"
    with pytest.raises(FoundationError) as e:
        F.simulate_game(H, TeamInput("AWY", H.players), random.Random(1))
    assert e.value.code == f"{S}_PLAYER_ON_BOTH_TEAMS"
    dup = TeamInput("HOM", (H.players[0], H.players[0]))
    with pytest.raises(FoundationError) as e:
        dup.validate()
    assert e.value.code == f"{S}_PLAYER_DUPLICATE"
    p = _paths(1)[0]
    with pytest.raises(FoundationError) as e:
        F.settle_player_prop(p, H, A, "PLAYER_POINTS", "AWY_p0", 9.5, "HOM")
    assert e.value.code == f"{S}_PLAYER_IDENTITY_MISMATCH"
    with pytest.raises(FoundationError):
        F.settle_player_prop(p, H, A, "PLAYER_POINTS", "HOM_p0", 9.5, "ZZZ")
    with pytest.raises(FoundationError):
        F.settle(p, "MONEYLINE", selection="ZZZ")
    with pytest.raises(FoundationError):
        F.settle(p, "TOTAL", line=1.5, segment="Q9")


@pytest.mark.parametrize("events,periods,code", [
    ([Event("HOM", "AWY_p0", 1, "FG2")], None, "PLAYER_NOT_ON_TEAM"),
    ([Event("ZZZ", "HOM_p0", 1, "FG2")], None, "EVENT_UNKNOWN_TEAM"),
    ([Event("HOM", "HOM_p0", 1, "FG4")], None, "EVENT_KIND_INVALID"),
    ([Event("HOM", "HOM_p0", 0, "FG2")], None, "PERIOD_INVALID"),
    ([Event("HOM", "HOM_p0", F.REG_PERIODS + 1, "FG2")], None, "PERIOD_INVALID"),
    ([], None, "GAME_ENDED_TIED"),
    ([Event("HOM", "HOM_p0", 1, "FG2"), Event("HOM", "HOM_p0", F.REG_PERIODS + 1, "FT")],
     F.REG_PERIODS + 1, "OT_AFTER_DECIDED_GAME"),
])
def test_impossible_paths_refused(events, periods, code):
    p = GamePath("HOM", "AWY", events)
    if periods:
        p.periods_played = periods
    with pytest.raises(FoundationError) as e:
        F.check_path(p, H, A)
    assert e.value.code == f"{S}_{code}"


def test_degenerate_zero_rates_refuse_instead_of_looping():
    with pytest.raises(FoundationError) as e:
        F.simulate_game(_team("HOM", 0.0), _team("AWY", 0.0), random.Random(1))
    assert e.value.code == f"{S}_OT_DID_NOT_RESOLVE"


def test_deterministic_given_seed():
    assert [p.final_score() for p in _paths(30, 4)] == [p.final_score() for p in _paths(30, 4)]


def test_terminal_map():
    for m in F.MARKET_TERMINALS:
        r = F.market_terminal(m)
        assert r["terminal"] in F.TERMINALS
        assert r["terminal"] not in ("VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD")
        assert r["probability"] is None and r["price"] is None and r["ev"] is None
        assert r["validation"] == "NO_VALIDATION"
    assert F.market_terminal("NOPE")["terminal"] == "NO_ENGINE"
    assert F.STATUS == "RESEARCH_ONLY"
    with pytest.raises(FoundationError) as e:
        F.settle(_paths(1)[0], "PLAYER_REBOUNDS", line=1.5)
    assert e.value.code == f"{S}_MARKET_NO_SETTLEMENT"


ILLINOIS = ["Illinois", "illinois fighting illini", "Northwestern", "DePaul", "Bradley",
            "Loyola Chicago", "Chicago State", "SIU Edwardsville", "UIC", "Northern Illinois"]


@pytest.mark.parametrize("name", ILLINOIS)
def test_illinois_college_names_blocked_everywhere(name):
    t = TeamInput(name, H.players[:1])
    with pytest.raises(FoundationError) as e:
        F.simulate_game(t, A, random.Random(1))
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
    r = F.market_terminal("MONEYLINE", name, "AWY")
    assert r["terminal"] == "BLOCKED_BY_AUTHORIZATION"
    assert r["reason"] == "ILLINOIS_COLLEGE_EXCLUDED"
    p = GamePath(name, "AWY", [])
    with pytest.raises(FoundationError) as e:
        F.settle(p, "TOTAL", line=1.5)
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"


@pytest.mark.parametrize("espn_id", ["356", "2130", "305", "71"])
def test_illinois_espn_ids_blocked_even_with_neutral_label(espn_id):
    t = TeamInput("TEAM_X", H.players[:1], espn_id=espn_id)
    with pytest.raises(FoundationError) as e:
        F.simulate_game(t, A, random.Random(1))
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"


@pytest.mark.parametrize("name", ["Northwestern State", "Indiana State", "Indiana"])
def test_non_illinois_lookalikes_not_blocked(name):
    assert F.market_terminal("MONEYLINE", name, "AWY")["terminal"] == "RESEARCH_ONLY"


def test_no_quarters_in_cbb():
    assert F.market_terminal("QUARTER_MARKETS")["terminal"] == "NOT_OFFERED"
    with pytest.raises(FoundationError):
        F.settle(_paths(1)[0], "TOTAL", segment="Q1", line=10.5)
