"""Regression tests for the either-pitcher Cartesian summation defect
found by the Stage 2 M31 dependence audit (REPORT_STAGE2.md section 4,
Amendment 1, AMENDMENT_M31_ULP_DISPOSITION.md).

Defect: the either branch summed the uniform-weight Cartesian state
weights with the builtin `sum` and derived the complement by
subtraction (1.0 - raw - raw_push). On full-coverage events the
accumulated sum is 1.0000000000000002 -- one floating-point ulp above
1 -- so the event mass exceeded 1 (or its complement was -2.2e-16)
and posterior_settlement_mass refused valid calls
(EmpiricalBayesError: settlement masses must be finite probabilities).
The audit census counted 110 refused calls over 68 real pairs out of
51,840 either-calls. math.fsum alone does NOT fix this: the exactly
rounded sum of the float products is itself 1.0000000000000002 for
e.g. 5x5 uniform pools (0.2*0.2 accumulated 25 times). The fix
follows Amendment 1 exactly: category masses are math.fsum sums of
the Cartesian state weights expressed as proportions of the fsum
total weight, so every mass is in [0, 1] by construction and the
probability is the module's own _posterior at those masses.

The EITHER_PITCHER family gate is untouched by the fix: pricing
stays refused at the card layer; this only stops the engine from
refusing valid computations.
"""
from __future__ import annotations

from math import fsum

import pytest

from sportsedge.mlb_empirical_bayes import effective_sample_size
from sportsedge.pitcher_joint_engine import (
    _normalize_pool,
    _posterior,
    _value,
    _weights,
    price_pitcher_market,
)

_BASE = {
    "EITHER_PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
    "EITHER_PITCHER_BB": "PITCHER_BB",
    "EITHER_PITCHER_ER": "PITCHER_ER",
}


def _start(k=5, outs=18, er=1, ha=6, bb=2, pitches=90):
    return {"strikeouts": k, "outs": outs, "earned_runs": er,
            "hits_allowed": ha, "walks_allowed": bb, "pitches": pitches}


def _const_pool(n, **kw):
    return [_start(**kw) for _ in range(n)]


def _disposition(pool_a, pool_b, market, side, line):
    """Amendment 1 disposition, independently recomputed: fsum
    category masses as proportions of the fsum total weight, the
    module's own _posterior, eff = min effective sample size."""
    a = _normalize_pool(pool_a, "pitcher_a_history")
    b = _normalize_pool(pool_b, "pitcher_b_history")
    wa = _weights(None, len(a), "pitcher_a_weights")
    wb = _weights(None, len(b), "pitcher_b_weights")
    base = _BASE[market]
    states = [(_value(x, base), _value(y, base), wx * wy)
              for x, wx in zip(a, wa) for y, wy in zip(b, wb)]

    def is_event(x, y):
        return (x > line or y > line) if side == "OVER" else (x < line or y < line)

    def is_push(x, y):
        if not float(line).is_integer() or is_event(x, y):
            return False
        return x == line or y == line

    total = fsum(w for _, _, w in states)
    p_event = fsum(w for x, y, w in states if is_event(x, y)) / total
    p_push = fsum(w for x, y, w in states if is_push(x, y)) / total
    p_comp = fsum(w for x, y, w in states
                  if not is_event(x, y) and not is_push(x, y)) / total
    eff = min(effective_sample_size(wa, len(wa)),
              effective_sample_size(wb, len(wb)))
    over, under = (p_event, p_comp) if side == "OVER" else (p_comp, p_event)
    post = _posterior(over, under, p_push, eff, line, base)
    return (float(post["p_over"] if side == "OVER" else post["p_under"]),
            float(post["p_push"]))


# (pool_a, pool_b, market, side, line) configurations that REFUSED on
# the pre-fix engine (builtin-sum overshoot on a full-coverage event
# or a full-coverage push category).
REFUSING_CONFIGS = [
    # audit shape: HA X+ 5 == OVER 4.5, every start in both pools >= 5
    (_const_pool(5, ha=8), _const_pool(5, ha=7),
     "EITHER_PITCHER_HITS_ALLOWED", "OVER", 4.5),
    (_const_pool(10, ha=8), _const_pool(10, ha=9),
     "EITHER_PITCHER_HITS_ALLOWED", "OVER", 4.5),
    # integer line, full-coverage PUSH category (every start == line)
    (_const_pool(10, bb=3), _const_pool(10, bb=3),
     "EITHER_PITCHER_BB", "OVER", 3),
    # or-fewer shape: UNDER at a high half line covers every state
    (_const_pool(10, bb=3), _const_pool(10, bb=2),
     "EITHER_PITCHER_BB", "UNDER", 11.5),
    (_const_pool(10, er=2), _const_pool(10, er=4),
     "EITHER_PITCHER_ER", "UNDER", 10.5),
]


@pytest.mark.parametrize("pool_a,pool_b,market,side,line", REFUSING_CONFIGS)
def test_full_coverage_either_calls_no_longer_refuse(pool_a, pool_b,
                                                     market, side, line):
    res = price_pitcher_market({
        "market": market, "side": side, "line": line,
        "features": {"pitcher_a_history": pool_a,
                     "pitcher_b_history": pool_b}})
    expected_p, expected_push = _disposition(pool_a, pool_b, market, side, line)
    assert abs(res["model_p"] - expected_p) <= 1e-12
    assert abs(res["push_p"] - expected_push) <= 1e-12
    assert 0.0 <= res["model_p"] <= 1.0
    assert 0.0 <= res["push_p"] <= 1.0


def test_full_coverage_raw_mass_is_exactly_one():
    res = price_pitcher_market({
        "market": "EITHER_PITCHER_HITS_ALLOWED", "side": "OVER", "line": 4.5,
        "features": {"pitcher_a_history": _const_pool(5, ha=8),
                     "pitcher_b_history": _const_pool(5, ha=7)}})
    # the fsum-proportion construction puts the full-coverage event
    # mass at exactly 1.0, not 1.0000000000000002
    assert res["meta"]["raw_empirical_p"] == 1.0
    assert res["meta"]["raw_push_p"] == 0.0


_VARIED_A = [
    _start(k=7, outs=19, er=2, ha=6, bb=1), _start(k=4, outs=15, er=4, ha=9, bb=3),
    _start(k=9, outs=21, er=1, ha=5, bb=2), _start(k=5, outs=17, er=3, ha=8, bb=0),
    _start(k=6, outs=18, er=2, ha=7, bb=4), _start(k=3, outs=14, er=5, ha=10, bb=2),
    _start(k=8, outs=20, er=0, ha=4, bb=1), _start(k=5, outs=16, er=3, ha=7, bb=3),
]
_VARIED_B = [
    _start(k=6, outs=18, er=2, ha=6, bb=2), _start(k=4, outs=15, er=4, ha=9, bb=1),
    _start(k=7, outs=19, er=1, ha=5, bb=3), _start(k=5, outs=17, er=3, ha=8, bb=2),
    _start(k=6, outs=16, er=2, ha=7, bb=0), _start(k=8, outs=20, er=0, ha=5, bb=2),
]

ORDINARY_CONFIGS = [
    (_VARIED_A, _VARIED_B, "EITHER_PITCHER_HITS_ALLOWED", "OVER", 6.5),
    (_VARIED_A, _VARIED_B, "EITHER_PITCHER_HITS_ALLOWED", "UNDER", 4.5),
    (_VARIED_A, _VARIED_B, "EITHER_PITCHER_BB", "OVER", 2),
    (_VARIED_A, _VARIED_B, "EITHER_PITCHER_BB", "UNDER", 2.5),
    (_VARIED_A, _VARIED_B, "EITHER_PITCHER_ER", "OVER", 3),
    (_VARIED_A, _VARIED_B, "EITHER_PITCHER_ER", "UNDER", 3.5),
    (_const_pool(7, ha=5, bb=1, er=0), _const_pool(9, ha=11, bb=5, er=6),
     "EITHER_PITCHER_HITS_ALLOWED", "OVER", 9.5),
    (_const_pool(7, ha=5, bb=1, er=0), _const_pool(9, ha=11, bb=5, er=6),
     "EITHER_PITCHER_ER", "UNDER", 0.5),
    # boundary shapes the pre-fix engine happened to answer: a 12x12
    # accumulation that lands exactly, and the event-empty boundary
    # (OVER above every state, complement mass exactly 1)
    (_const_pool(12, ha=6), _const_pool(12, ha=6),
     "EITHER_PITCHER_HITS_ALLOWED", "OVER", 5.5),
    (_const_pool(5, ha=8), _const_pool(5, ha=7),
     "EITHER_PITCHER_HITS_ALLOWED", "OVER", 20),
]


@pytest.mark.parametrize("pool_a,pool_b,market,side,line", ORDINARY_CONFIGS)
def test_either_probabilities_match_amendment1_disposition(pool_a, pool_b,
                                                           market, side, line):
    res = price_pitcher_market({
        "market": market, "side": side, "line": line,
        "features": {"pitcher_a_history": pool_a,
                     "pitcher_b_history": pool_b}})
    expected_p, expected_push = _disposition(pool_a, pool_b, market, side, line)
    assert abs(res["model_p"] - expected_p) <= 1e-12
    assert abs(res["push_p"] - expected_push) <= 1e-12


# Non-either branches: outputs pinned from the pre-fix engine
# (blob 00cba6f6 at main 56c1c8f1f). The summation fix is confined to
# the either branch; every value below must reproduce EXACTLY.
_POOL = _VARIED_A
_PRIOR = _VARIED_A + [
    _start(k=6, outs=18, er=2, ha=6, bb=2, pitches=95),
    _start(k=4, outs=15, er=4, ha=9, bb=1, pitches=87),
    _start(k=7, outs=19, er=1, ha=5, bb=3, pitches=98),
    _start(k=5, outs=17, er=3, ha=8, bb=2, pitches=90),
]
for _row in _POOL:
    _row.setdefault("pitches", 90)
_POOL[0]["pitches"] = 96
_POOL[1]["pitches"] = 88
_POOL[2]["pitches"] = 104
_POOL[3]["pitches"] = 91
_POOL[4]["pitches"] = 99
_POOL[5]["pitches"] = 82
_POOL[6]["pitches"] = 101
_POOL[7]["pitches"] = 93

NON_EITHER_PINNED = [
    ({"market": "PITCHER_K", "side": "OVER", "line": 5.5,
      "features": {"history_pool": _POOL}}, 0.5, 0.0),
    ({"market": "PITCHER_OUTS", "side": "UNDER", "line": 17.5,
      "features": {"history_pool": _POOL}}, 0.5, 0.0),
    ({"market": "PITCHER_PITCHES", "side": "OVER", "line": 90.5,
      "features": {"history_pool": _POOL}}, 0.7222222222222222, 0.0),
    ({"market": "PITCHER_ER", "side": "OVER", "line": 2.5,
      "features": {"history_pool": _POOL, "prior_pool": _PRIOR}}, 0.5, 0.0),
    ({"market": "PITCHER_HITS_ALLOWED", "side": "UNDER", "line": 6.5,
      "features": {"history_pool": _POOL, "prior_pool": _PRIOR}},
     0.40196078431372545, 0.0),
    ({"market": "PITCHER_HITS_WALKS_ER", "side": "OVER", "line": 10.5,
      "features": {"history_pool": _POOL, "prior_pool": _PRIOR}},
     0.5980392156862745, 0.0),
    ({"market": "PITCHER_K", "side": "OVER", "line": 4.5,
      "features": {"history_pool": _POOL[:3],
                   "prior_fallback": {"market": "PITCHER_K",
                                      "pseudo_starts": 6,
                                      "counts": {"2": 4, "4": 9, "6": 12,
                                                 "8": 6, "10": 2},
                                      "pool": "league", "season": 2025,
                                      "artifact_sha256": "x"}}},
     0.6136363636363636, 0.0),
    ({"market": "PITCHER_K", "side": "OVER", "line": 5.5,
      "features": {"history_pool": _POOL,
                   "opp_k_adjustment": {"market": "PITCHER_K", "beta": 0.5,
                                        "target_rel": 1.1,
                                        "history_rel": [0.9, 1.0, 1.2, 0.8,
                                                        1.05, 0.95, 1.15, 1.0]}}},
     0.6230071045144495, 0.0),
]


@pytest.mark.parametrize("model_input,expected_p,expected_push", NON_EITHER_PINNED)
def test_non_either_branches_unchanged(model_input, expected_p, expected_push):
    res = price_pitcher_market(model_input)
    assert res["model_p"] == expected_p
    assert res["push_p"] == expected_push
