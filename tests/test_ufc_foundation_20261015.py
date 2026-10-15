"""Synthetic-fixture tests for the research-only UFC foundation (no real data)."""
import random

import pytest

from sportsedge.research import ufc_foundation as F
from sportsedge.research.ufc_foundation import BoutPath, FighterInput, FoundationError

R = FighterInput("RED", 0.12, 0.05, 1.2)
B = FighterInput("BLU", 0.08, 0.07, 1.0)


def _bouts(n=2000, seed=3, rounds=3):
    rng = random.Random(seed)
    return [F.simulate_bout(R, B, rng, scheduled_rounds=rounds) for _ in range(n)]


@pytest.mark.parametrize("rounds", [3, 5])
def test_every_bout_has_exactly_one_coherent_result(rounds):
    methods = set()
    for b in _bouts(rounds=rounds):
        assert F.check_bout(b)
        methods.add(b.method)
        if b.method in F.FINISH_METHODS:
            assert b.end_round <= rounds and 0 < b.end_second <= F.ROUND_SEC
        else:
            assert (b.end_round, b.end_second) == (rounds, F.ROUND_SEC)
    assert {"KO_TKO", "SUBMISSION", "UNANIMOUS"} <= methods


def test_markets_mutually_consistent():
    for b in _bouts():
        ml = {f: F.settle(b, "MONEYLINE", selection=f) for f in ("RED", "BLU")}
        if b.method == "DRAW":
            assert set(ml.values()) == {"VOID"}
            continue
        assert sorted(ml.values()) == ["LOSE", "WIN"]
        mov = [(f, h) for f in ("RED", "BLU") for h in ("KO_TKO_DQ", "SUBMISSION", "DECISION")
               if F.settle(b, "METHOD_OF_VICTORY", selection=(f, h)) == "WIN"]
        assert len(mov) == 1 and mov[0][0] == b.winner
        rb = [(f, r) for f in ("RED", "BLU") for r in range(1, b.scheduled_rounds + 1)
              if F.settle(b, "ROUND_BETTING", selection=f, round_no=r) == "WIN"]
        dist = F.settle(b, "GOES_THE_DISTANCE", selection="YES") == "WIN"
        assert (len(rb) == 0) == dist


def test_total_rounds_half_point_boundary():
    at = BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 3, 150)
    before = BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 3, 149)
    assert F.settle(at, "TOTAL_ROUNDS", line=2.5) == "OVER"
    assert F.settle(before, "TOTAL_ROUNDS", line=2.5) == "UNDER"
    r1 = BoutPath("RED", "BLU", 3, "SUBMISSION", "BLU", 1, 151)
    assert F.settle(r1, "TOTAL_ROUNDS", line=0.5) == "OVER"
    assert F.settle(r1, "TOTAL_ROUNDS", line=1.5) == "UNDER"
    dec = BoutPath("RED", "BLU", 3, "UNANIMOUS", "RED", 3, 300)
    assert F.settle(dec, "TOTAL_ROUNDS", line=2.5) == "OVER"


def test_draw_and_no_contest_void():
    d = BoutPath("RED", "BLU", 3, "DRAW", None, 3, 300)
    assert F.settle(d, "MONEYLINE", selection="RED") == "VOID"
    assert F.settle(d, "METHOD_OF_VICTORY", selection=("RED", "DECISION")) == "VOID"
    assert F.settle(d, "GOES_THE_DISTANCE", selection="YES") == "WIN"
    nc = BoutPath("RED", "BLU", 5, "NO_CONTEST", None, 2, 30)
    for m in ("MONEYLINE", "TOTAL_ROUNDS", "GOES_THE_DISTANCE", "ROUND_BETTING"):
        assert F.settle(nc, m, selection="RED", line=1.5, round_no=1) == "VOID"


def test_dq_settles_with_ko_tko():
    b = BoutPath("RED", "BLU", 3, "DQ", "BLU", 2, 200)
    assert F.settle(b, "METHOD_OF_VICTORY", selection=("BLU", "KO_TKO_DQ")) == "WIN"


@pytest.mark.parametrize("bout,code", [
    (BoutPath("RED", "BLU", 4, "KO_TKO", "RED", 1, 10), "UFC_SCHEDULED_ROUNDS_INVALID"),
    (BoutPath("RED", "RED", 3, "KO_TKO", "RED", 1, 10), "UFC_FIGHTER_IDENTITY_COLLISION"),
    (BoutPath("RED", "BLU", 3, "KO", "RED", 1, 10), "UFC_METHOD_INVALID"),
    (BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 4, 10), "UFC_ROUND_INVALID"),
    (BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 1, 301), "UFC_TIME_INVALID"),
    (BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 1, 0), "UFC_TIME_INVALID"),
    (BoutPath("RED", "BLU", 3, "KO_TKO", "GRN", 1, 10), "UFC_WINNER_IDENTITY_MISMATCH"),
    (BoutPath("RED", "BLU", 3, "KO_TKO", None, 1, 10), "UFC_WINNER_IDENTITY_MISMATCH"),
    (BoutPath("RED", "BLU", 3, "UNANIMOUS", "RED", 2, 300), "UFC_DECISION_BEFORE_FINAL_BELL"),
    (BoutPath("RED", "BLU", 5, "SPLIT", "RED", 3, 300), "UFC_DECISION_BEFORE_FINAL_BELL"),
    (BoutPath("RED", "BLU", 3, "DRAW", "RED", 3, 300), "UFC_DRAW_WITH_WINNER"),
    (BoutPath("RED", "BLU", 3, "NO_CONTEST", "RED", 1, 10), "UFC_NO_CONTEST_WITH_WINNER"),
])
def test_impossible_bouts_refused(bout, code):
    with pytest.raises(FoundationError) as e:
        F.check_bout(bout)
    assert e.value.code == code


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, True, None])
def test_nonfinite_inputs_refused(bad):
    with pytest.raises(FoundationError):
        F.simulate_bout(FighterInput("RED", bad, 0.1, 1.0), B, random.Random(1))
    with pytest.raises(FoundationError):
        F.simulate_bout(R, B, random.Random(1), draw_prob=bad)


def test_out_of_range_inputs_refused():
    with pytest.raises(FoundationError) as e:
        F.simulate_bout(FighterInput("RED", 0.6, 0.5, 1.0), B, random.Random(1))
    assert e.value.code == "UFC_INPUT_OUT_OF_RANGE"
    with pytest.raises(FoundationError):
        F.simulate_bout(R, B, random.Random(1), scheduled_rounds=4)
    with pytest.raises(FoundationError):
        F.simulate_bout(FighterInput("RED", 0.1, 0.1, 0.0), B, random.Random(1))
    with pytest.raises(FoundationError) as e:
        F.simulate_bout(R, FighterInput("RED", 0.1, 0.1, 1.0), random.Random(1))
    assert e.value.code == "UFC_FIGHTER_IDENTITY_COLLISION"


def test_settlement_refusals():
    b = BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 1, 10)
    with pytest.raises(FoundationError):
        F.settle(b, "MONEYLINE", selection="GRN")
    with pytest.raises(FoundationError):
        F.settle(b, "METHOD_OF_VICTORY", selection=("RED", "KO"))
    with pytest.raises(FoundationError):
        F.settle(b, "ROUND_BETTING", selection="RED", round_no=4)
    for bad in (float("nan"), float("inf"), 2, 3.5, True, None, -0.5):
        with pytest.raises(FoundationError):
            F.settle(b, "TOTAL_ROUNDS", line=bad)
    with pytest.raises(FoundationError) as e:
        F.settle(b, "SIGNIFICANT_STRIKES", line=50.5)
    assert e.value.code == "UFC_MARKET_NO_SETTLEMENT"


def test_terminal_map():
    for m in F.MARKET_TERMINALS:
        r = F.market_terminal(m)
        assert r["terminal"] in F.TERMINALS
        assert r["terminal"] not in ("VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD")
        assert r["probability"] is None and r["price"] is None and r["ev"] is None
    assert F.market_terminal("X")["terminal"] == "NO_ENGINE"
    assert F.STATUS == "RESEARCH_ONLY" and F.VALIDATION == "NO_VALIDATION"
