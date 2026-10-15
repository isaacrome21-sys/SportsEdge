"""Synthetic-fixture tests for the research-only PGA hole layer (no real data)."""
import random

import pytest

from sportsedge.research import pga_foundation as F
from sportsedge.research import pga_foundation_props as P
from sportsedge.research.pga_foundation import FoundationError, PlayerInput, TournamentPath

PARS = (4, 4, 3, 5, 4, 4, 3, 4, 5, 4, 4, 3, 5, 4, 4, 3, 4, 5)   # synthetic par 72
FIELD = [PlayerInput(f"P{i:03d}", 70.0 + i * 0.02, 3.0) for i in range(80)]


def _hp(seed=1):
    t = F.simulate_tournament(FIELD, random.Random(seed))
    return P.simulate_holes(t, PARS, random.Random(seed))


def test_holes_sum_to_round_scores():
    for seed in range(5):
        hp = _hp(seed)
        assert P.check_holes(hp)
        for pid, rs in hp.tournament.rounds.items():
            for r, total in enumerate(rs):
                assert sum(hp.holes[(pid, r)]) == total
            assert sum(sum(hp.holes[(pid, r)]) for r in range(len(rs))) == hp.tournament.total(pid)


def test_type_counts_partition_holes_and_settle():
    hp = _hp(2)
    for pid, rs in hp.tournament.rounds.items():
        c = hp.counts(pid)
        assert sum(c.values()) == 18 * len(rs)
        b = c["EAGLE_OR_BETTER"] + c["BIRDIE"]
        assert P.settle_prop(hp, "PLAYER_BIRDIES", player_id=pid, line=b) == "PUSH"
        bo = c["BOGEY"] + c["DOUBLE_OR_WORSE"]
        assert P.settle_prop(hp, "PLAYER_BOGEYS", player_id=pid, line=bo - 0.5) == \
            ("OVER" if bo > bo - 0.5 else "UNDER")


def test_score_noise_produces_birdies_and_bogeys():
    hp = _hp(3)
    tot = {t: 0 for t in P.TYPES}
    for pid in hp.tournament.rounds:
        for k, v in hp.counts(pid).items():
            tot[k] += v
    assert tot["BIRDIE"] > 0 and tot["BOGEY"] > 0


def test_unplayed_rounds_void_and_hole_market():
    hp = _hp(4)
    missed = next(p for p in hp.tournament.rounds if p not in hp.tournament.made_cut)
    assert P.settle_prop(hp, "PLAYER_BIRDIES", player_id=missed, line=2.5, round_index=3) == "VOID"
    pid = hp.tournament.winner
    s = hp.holes[(pid, 0)][0]
    yes = P.settle_prop(hp, "HOLE_BIRDIE_OR_BETTER", player_id=pid, round_index=0, hole=1,
                        selection="YES")
    assert yes == ("WIN" if s < PARS[0] else "LOSE")


def test_prestart_wd_void():
    t = TournamentPath({"A": [70, 70, 70, 70], "X": []}, {"A"}, {"X": 0}, winner="A")
    hp = P.simulate_holes(t, PARS, random.Random(1))
    assert P.settle_prop(hp, "PLAYER_BIRDIES", player_id="X", line=3.5) == "VOID"


@pytest.mark.parametrize("pars,code", [
    (PARS[:17], "PGA_COURSE_HOLES_INVALID"),
    (PARS[:17] + (6,), "PGA_PAR_INVALID"),
    (PARS[:17] + (4.0,), "PGA_PAR_INVALID"),
    (PARS[:17] + (True,), "PGA_PAR_INVALID"),
    ("par72", "PGA_COURSE_HOLES_INVALID"),
])
def test_bad_course_refused(pars, code):
    t = F.simulate_tournament(FIELD[:5], random.Random(1))
    with pytest.raises(FoundationError) as e:
        P.simulate_holes(t, pars, random.Random(1))
    assert e.value.code == code


@pytest.mark.parametrize("mutate,code", [
    (lambda hp, k: hp.holes.__setitem__(k, hp.holes[k][:17]), "PGA_HOLE_COUNT_INVALID"),
    (lambda hp, k: hp.holes.__setitem__(k, (0,) + hp.holes[k][1:]), "PGA_HOLE_SCORE_INVALID"),
    (lambda hp, k: hp.holes.__setitem__(k, (99,) + hp.holes[k][1:]), "PGA_HOLE_SCORE_INVALID"),
    (lambda hp, k: hp.holes.__setitem__(k, (float("nan"),) + hp.holes[k][1:]),
     "PGA_HOLE_SCORE_INVALID"),
    (lambda hp, k: hp.holes.__setitem__(k, (hp.holes[k][0] + 1,) + hp.holes[k][1:]),
     "PGA_HOLES_NOT_CONSERVED"),
    (lambda hp, k: hp.holes.pop(k), "PGA_HOLE_ROUNDS_MISMATCH"),
    (lambda hp, k: hp.holes.__setitem__(("P000", 3), hp.holes[k]) if ("P000", 3) not in hp.holes
     else hp.holes.__setitem__(("P000", 4), hp.holes[k]), "PGA_HOLE_ROUNDS_MISMATCH"),
])
def test_tampered_holes_refused(mutate, code):
    hp = _hp(5)
    mutate(hp, ("P001", 0))
    with pytest.raises(FoundationError) as e:
        P.check_holes(hp)
    assert e.value.code == code


def test_infeasible_round_refused():
    t = TournamentPath({"A": [70, 70, 70, 70]}, {"A"}, winner="A")
    with pytest.raises(FoundationError) as e:
        P._round_holes(random.Random(1), 17, PARS, 0)
    assert e.value.code == "PGA_ROUND_SCORE_INFEASIBLE"
    with pytest.raises(FoundationError):
        P._round_holes(random.Random(1), sum(PARS) + 18 * P.MAX_OVER_PAR + 1, PARS, 0)
    assert P.check_holes(P.simulate_holes(t, PARS, random.Random(1)))


def test_settlement_refusals():
    hp = _hp(6)
    with pytest.raises(FoundationError):
        P.settle_prop(hp, "PLAYER_BIRDIES", player_id="NOBODY", line=3.5)
    for ln in (float("nan"), float("inf"), None, True):
        with pytest.raises(FoundationError):
            P.settle_prop(hp, "PLAYER_BIRDIES", player_id="P000", line=ln)
    for ri in (-1, 4, 1.0, True):
        with pytest.raises(FoundationError):
            P.settle_prop(hp, "PLAYER_BIRDIES", player_id="P000", line=3.5, round_index=ri)
    for hole, sel in ((0, "YES"), (19, "YES"), (1, "MAYBE"), (True, "YES")):
        with pytest.raises(FoundationError):
            P.settle_prop(hp, "HOLE_BIRDIE_OR_BETTER", player_id="P000", round_index=0,
                          hole=hole, selection=sel)
    with pytest.raises(FoundationError):
        P.simulate_holes(hp.tournament, PARS, random.Random(1), swaps=-1)
    with pytest.raises(FoundationError) as e:
        P.settle_prop(hp, "HOLE_IN_ONE", player_id="P000")
    assert e.value.code == "PGA_MARKET_NO_SETTLEMENT"


def test_status_and_map():
    assert P.STATUS == "RESEARCH_ONLY" and P.VALIDATION == "NO_VALIDATION"
    for m in ("HOLE_PROPS", "BIRDIES_PROPS"):
        r = F.market_terminal(m)
        assert r["terminal"] == "RESEARCH_ONLY" and r["probability"] is None
