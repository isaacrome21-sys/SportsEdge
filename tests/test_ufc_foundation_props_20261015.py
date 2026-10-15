"""Synthetic-fixture tests for the research-only UFC stats layer (no real data)."""
import random

import pytest

from sportsedge.research import ufc_foundation as F
from sportsedge.research import ufc_foundation_props as P
from sportsedge.research.ufc_foundation import BoutPath, FighterInput, FoundationError
from sportsedge.research.ufc_foundation_props import FighterStatsInput, StatsPath

R = FighterInput("RED", 0.12, 0.05, 1.2)
B = FighterInput("BLU", 0.08, 0.07, 1.0)
RS = FighterStatsInput("RED", 4.5, 2.0, 0.45, 0.02)
BS = FighterStatsInput("BLU", 3.8, 1.0, 0.35, 0.015)


def _paths(n=400, seed=8, rounds=3):
    rng = random.Random(seed)
    return [P.simulate_stats(F.simulate_bout(R, B, rng, scheduled_rounds=rounds), RS, BS, rng)
            for _ in range(n)]


@pytest.mark.parametrize("rounds", [3, 5])
def test_stats_only_for_rounds_fought_and_sum(rounds):
    for p in _paths(rounds=rounds):
        assert P.check_stats(p)
        b = p.bout
        assert {r for (_, r) in p.rounds} == set(range(1, b.end_round + 1))
        for f in ("RED", "BLU"):
            for s in P.STATS:
                assert p.total(f, s) == sum(p.rounds[(f, r)][s] for r in range(1, b.end_round + 1))
            assert p.total(f, "KD") <= p.total(f, "SIG")
            assert p.total(f, "TD") <= p.total(f, "TDA")


def test_ko_winner_always_landed_in_final_round():
    seen = 0
    for p in _paths(800):
        if p.bout.method == "KO_TKO":
            seen += 1
            assert p.rounds[(p.bout.winner, p.bout.end_round)]["SIG"] >= 1
    assert seen > 0


def test_short_finish_scales_exposure():
    b = BoutPath("RED", "BLU", 3, "SUBMISSION", "RED", 1, 1)
    hi = FighterStatsInput("RED", 0.0, 0.0, 0.0, 0.0)
    for s in range(200):
        p = P.simulate_stats(b, hi, FighterStatsInput("BLU", 0.0, 0.0, 0.0, 0.0), random.Random(s))
        assert p.total("RED", "SIG") == 0 and p.total("BLU", "TD") == 0


def test_settlement_and_no_contest_void():
    p = _paths(1)[0]
    v = p.total("RED", "SIG")
    assert P.settle_stat(p, "SIGNIFICANT_STRIKES", fighter_id="RED", line=v) == "PUSH"
    assert P.settle_stat(p, "SIGNIFICANT_STRIKES", fighter_id="RED", line=v - 0.5) == "OVER"
    nc = BoutPath("RED", "BLU", 3, "NO_CONTEST", None, 2, 40)
    q = P.simulate_stats(nc, RS, BS, random.Random(1))
    for m in P.PROPS_MARKETS:
        assert P.settle_stat(q, m, fighter_id="BLU", line=0.5) == "VOID"


def _fixed():
    b = BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 2, 60)
    return P.simulate_stats(b, RS, BS, random.Random(4))


@pytest.mark.parametrize("mutate,code", [
    (lambda p: p.rounds.__setitem__(("RED", 3), dict(p.rounds[("RED", 1)])),
     "UFC_STATS_ROUND_NOT_FOUGHT"),
    (lambda p: p.rounds.pop(("BLU", 1)), "UFC_STATS_ROUND_MISSING"),
    (lambda p: p.rounds[("RED", 1)].__setitem__("KD", p.rounds[("RED", 1)]["SIG"] + 1),
     "UFC_KNOCKDOWNS_EXCEED_STRIKES"),
    (lambda p: p.rounds[("BLU", 1)].__setitem__("TD", p.rounds[("BLU", 1)]["TDA"] + 1),
     "UFC_TAKEDOWNS_EXCEED_ATTEMPTS"),
    (lambda p: p.rounds[("RED", 2)].update(SIG=0, KD=0), "UFC_KO_WITHOUT_STRIKE"),
    (lambda p: p.rounds[("RED", 1)].__setitem__("SIG", -1), "UFC_STATS_COUNT_INVALID"),
    (lambda p: p.rounds[("RED", 1)].__setitem__("SIG", float("nan")), "UFC_STATS_COUNT_INVALID"),
    (lambda p: p.rounds[("RED", 1)].pop("TDA"), "UFC_STATS_FIELDS_INVALID"),
])
def test_tampered_stats_refused(mutate, code):
    p = _fixed()
    assert P.check_stats(p)
    mutate(p)
    with pytest.raises(FoundationError) as e:
        P.check_stats(p)
    assert e.value.code == code


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True, None])
def test_nonfinite_inputs_refused(bad):
    b = BoutPath("RED", "BLU", 3, "UNANIMOUS", "RED", 3, 300)
    with pytest.raises(FoundationError):
        P.simulate_stats(b, FighterStatsInput("RED", bad, 1.0, 0.5, 0.01), BS, random.Random(1))
    with pytest.raises(FoundationError):
        P.simulate_stats(b, FighterStatsInput("RED", 1.0, 1.0, bad, 0.01), BS, random.Random(1))


def test_identity_and_range_refusals():
    b = BoutPath("RED", "BLU", 3, "UNANIMOUS", "RED", 3, 300)
    with pytest.raises(FoundationError) as e:
        P.simulate_stats(b, BS, RS, random.Random(1))
    assert e.value.code == "UFC_STATS_IDENTITY_MISMATCH"
    with pytest.raises(FoundationError):
        P.simulate_stats(b, FighterStatsInput("RED", 1.0, 1.0, 1.5, 0.0), BS, random.Random(1))
    p = P.simulate_stats(b, RS, BS, random.Random(1))
    with pytest.raises(FoundationError):
        P.settle_stat(p, "TAKEDOWNS", fighter_id="GRN", line=1.5)
    for ln in (float("nan"), float("inf"), None, True):
        with pytest.raises(FoundationError):
            P.settle_stat(p, "TAKEDOWNS", fighter_id="RED", line=ln)
    with pytest.raises(FoundationError) as e:
        P.settle_stat(p, "CONTROL_TIME", fighter_id="RED", line=1.5)
    assert e.value.code == "UFC_MARKET_NO_SETTLEMENT"
    with pytest.raises(FoundationError):
        P.simulate_stats(BoutPath("RED", "BLU", 3, "UNANIMOUS", "RED", 2, 300), RS, BS,
                         random.Random(1))


def test_status_and_map():
    assert P.STATUS == "RESEARCH_ONLY" and P.VALIDATION == "NO_VALIDATION"
    for m in P.PROPS_MARKETS:
        r = F.market_terminal(m)
        assert r["terminal"] == "RESEARCH_ONLY" and r["probability"] is None
