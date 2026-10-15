"""Synthetic-fixture tests for the research-only PGA foundation (no real data)."""
import random
from fractions import Fraction

import pytest

from sportsedge.research import pga_foundation as F
from sportsedge.research.pga_foundation import FoundationError, PlayerInput, TournamentPath

FIELD = [PlayerInput(f"P{i:03d}", 70.0 + i * 0.02, 3.0) for i in range(120)]


def _paths(n=40, seed=1, field=FIELD):
    rng = random.Random(seed)
    return [F.simulate_tournament(field, rng) for _ in range(n)]


def test_conservation_and_cut():
    for p in _paths():
        assert F.check_path(p)
        assert len(p.made_cut) >= 65
        for pid, rs in p.rounds.items():
            assert p.total(pid) == sum(rs)
            assert len(rs) == (4 if pid in p.made_cut else 2)


def test_exactly_one_outright_winner_even_with_ties():
    for p in _paths():
        wins = [pid for pid in p.rounds if F.settle(p, "OUTRIGHT", player_id=pid)[0] == "WIN"]
        assert wins == [p.winner]


@pytest.mark.parametrize("n", [1, 5, 10, 20])
def test_top_n_dead_heat_stakes_sum_to_n(n):
    for p in _paths(20):
        total = Fraction(0)
        for pid in p.rounds:
            r, frac = F.settle(p, "TOP_N", player_id=pid, n=n)
            if r == "WIN":
                total += frac
        assert total == n


def test_dead_heat_fraction_explicit():
    r = {"A": [70, 70, 70, 65], "B": [70, 70, 70, 66], "C": [70, 70, 70, 66],
         "D": [70, 70, 70, 66], "E": [80, 80]}
    p = TournamentPath(r, {"A", "B", "C", "D"}, winner="A")
    assert F.settle(p, "TOP_N", player_id="B", n=2) == ("WIN", Fraction(1, 3))
    assert F.settle(p, "TOP_N", player_id="A", n=2) == ("WIN", Fraction(1))
    assert F.settle(p, "TOP_N", player_id="E", n=4) == ("LOSE", Fraction(1))


def test_playoff_winner_beats_tied_coleader_for_outright_but_positions_stay_coherent():
    r = {"A": [70, 70, 70, 66], "B": [70, 70, 70, 66], "C": [80, 80]}
    p = TournamentPath(r, {"A", "B"}, winner="B")
    assert F.settle(p, "OUTRIGHT", player_id="B")[0] == "WIN"
    assert F.settle(p, "OUTRIGHT", player_id="A")[0] == "LOSE"
    assert F.settle(p, "TOP_N", player_id="A", n=2) == ("WIN", Fraction(1))


def test_matchup_rules():
    r = {"A": [70, 70, 70, 70], "B": [70, 70, 70, 70], "C": [80, 80], "D": [72, 72, 72, 60]}
    p = TournamentPath(r, {"A", "B", "D"}, winner="D")
    assert F.settle(p, "MATCHUP", player_id="A", opponent_id="B")[0] == "PUSH"
    assert F.settle(p, "MATCHUP", player_id="A", opponent_id="C")[0] == "WIN"
    assert F.settle(p, "MATCHUP", player_id="C", opponent_id="A")[0] == "LOSE"
    wd = TournamentPath({"A": [70, 70, 70, 70], "W": [71], "X": [], "Z": [75, 75]},
                        {"A"}, {"W": 2, "X": 0}, winner="A")   # 1 completed round => WD in R2
    assert F.check_path(wd)
    assert F.settle(wd, "MATCHUP", player_id="A", opponent_id="W")[0] == "WIN"
    assert F.settle(wd, "MATCHUP", player_id="W", opponent_id="A")[0] == "LOSE"
    assert F.settle(wd, "MATCHUP", player_id="A", opponent_id="X")[0] == "VOID"
    assert F.settle(wd, "MAKE_CUT", player_id="X")[0] == "VOID"
    assert F.settle(wd, "OUTRIGHT", player_id="X")[0] == "VOID"
    assert F.settle(wd, "MAKE_CUT", player_id="W")[0] == "LOSE"


def test_prestart_wd_simulated():
    field = FIELD[:10] + [PlayerInput("WDX", 70.0, 3.0, wd_before_start=True)]
    p = _paths(1, field=field)[0]
    assert p.rounds["WDX"] == [] and p.withdrawn["WDX"] == 0
    assert F.settle(p, "TOP_N", player_id="WDX", n=5)[0] == "VOID"


@pytest.mark.parametrize("rounds,made,wd,winner,code", [
    ({"A": [70, 70, 70, 70, 70]}, {"A"}, {}, "A", "PGA_ROUND_COUNT_INVALID"),
    ({"A": [70, 70, 70, 40]}, {"A"}, {}, "A", "PGA_ROUND_SCORE_INVALID"),
    ({"A": [70, 70, 70, 70.5]}, {"A"}, {}, "A", "PGA_ROUND_SCORE_INVALID"),
    ({"A": [70, 70, 70, 70], "B": [70]}, {"A"}, {"B": 0}, "A", "PGA_PRESTART_WD_HAS_SCORES"),
    ({"A": [70, 70, 70]}, {"A"}, {}, "A", "PGA_FINISHER_ROUND_COUNT"),
    ({"A": [70, 70, 70, 70], "B": [80, 80, 70]}, {"A"}, {}, "A", "PGA_MISSED_CUT_PLAYED_WEEKEND"),
    ({"A": [70, 70, 70, 70], "B": [60, 60]}, {"A"}, {}, "A", "PGA_CUT_INCOHERENT"),
    ({"A": [70, 70, 70, 70], "B": [80, 80]}, {"A"}, {}, "B", "PGA_WINNER_IDENTITY_MISMATCH"),
    ({"A": [70, 70, 70, 70], "B": [70, 70, 70, 69]}, {"A", "B"}, {}, "A", "PGA_WINNER_NOT_LOW_SCORE"),
    ({"A": [70, 70, 70, 70]}, {"A", "Q"}, {}, "A", "PGA_PLAYER_IDENTITY_MISMATCH"),
])
def test_impossible_paths_refused(rounds, made, wd, winner, code):
    with pytest.raises(FoundationError) as e:
        F.check_path(TournamentPath(rounds, made, wd, winner))
    assert e.value.code == code


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True, None])
def test_nonfinite_inputs_refused(bad):
    with pytest.raises(FoundationError):
        F.simulate_tournament([PlayerInput("A", 70.0, bad), FIELD[1]], random.Random(1))
    with pytest.raises(FoundationError):
        F.simulate_tournament([PlayerInput("A", bad, 3.0), FIELD[1]], random.Random(1))


def test_identity_and_param_refusals():
    with pytest.raises(FoundationError) as e:
        F.simulate_tournament([FIELD[0], FIELD[0]], random.Random(1))
    assert e.value.code == "PGA_PLAYER_DUPLICATE"
    with pytest.raises(FoundationError):
        F.simulate_tournament(FIELD, random.Random(1), cut_top=0)
    p = _paths(1)[0]
    with pytest.raises(FoundationError):
        F.settle(p, "OUTRIGHT", player_id="NOBODY")
    with pytest.raises(FoundationError):
        F.settle(p, "MATCHUP", player_id="P000", opponent_id="P000")
    for bad in (0, -3, 2.5, True, None):
        with pytest.raises(FoundationError):
            F.settle(p, "TOP_N", player_id="P000", n=bad)
    with pytest.raises(FoundationError) as e:
        F.settle(p, "THREE_BALL", player_id="P000")
    assert e.value.code == "PGA_MARKET_NO_SETTLEMENT"


def test_terminal_map():
    for m in F.MARKET_TERMINALS:
        r = F.market_terminal(m)
        assert r["terminal"] in F.TERMINALS
        assert r["terminal"] not in ("VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD")
        assert r["probability"] is None and r["price"] is None and r["ev"] is None
    assert F.market_terminal("X")["terminal"] == "NO_ENGINE"
    assert F.STATUS == "RESEARCH_ONLY" and F.VALIDATION == "NO_VALIDATION"
