"""Parity: generic_market_engine game settlement == shared MLB readout.

generic_market_engine._game_probability used to settle MONEYLINE / RUN_LINE /
TOTALS / TEAM_TOTALS with its own copy of the joint-PMF arithmetic. It now
calls game_distribution_readout.read_game_probability. ``_legacy_settle``
below is a verbatim copy of the removed arithmetic (oracle). Every assertion
is exact equality (==), not approximate, across many lines including
whole-number pushes, alternates and both sides.
"""
from __future__ import annotations

import hashlib
import random

import pytest

from sportsedge import generic_market_engine as ge
from sportsedge import v7_distribution as v7
from sportsedge.game_distribution_readout import read_game_probability


def _legacy_settle(pmf, market, side, line, team_side=None):
    states = ge._joint_states(pmf)
    p_push = 0.0
    if market == "MONEYLINE":
        if side in {"HOME", "HOME_ML"}:
            p = sum(prob for away, home, prob in states if home > away)
        else:
            p = sum(prob for away, home, prob in states if away > home)
    elif market == "RUN_LINE":
        if side in {"HOME", "HOME_RL"}:
            adjusted = [(home - away) + line for away, home, _ in states]
        else:
            adjusted = [(away - home) + line for away, home, _ in states]
        p = sum(prob for (_, _, prob), value in zip(states, adjusted) if value > 0)
        p_push = sum(prob for (_, _, prob), value in zip(states, adjusted) if abs(value) < 1e-12)
    elif market == "TOTALS":
        if side == "OVER":
            p = sum(prob for away, home, prob in states if away + home > line)
        else:
            p = sum(prob for away, home, prob in states if away + home < line)
        p_push = sum(prob for away, home, prob in states if abs((away + home) - line) < 1e-12)
    else:
        values = [home if team_side == "HOME" else away for away, home, _ in states]
        if side == "OVER":
            p = sum(prob for (_, _, prob), value in zip(states, values) if value > line)
        else:
            p = sum(prob for (_, _, prob), value in zip(states, values) if value < line)
        p_push = sum(prob for (_, _, prob), value in zip(states, values) if abs(value - line) < 1e-12)
    return float(p), float(p_push)


RL_LINES = [x / 2 for x in range(-12, 13)]          # -6.0 .. +6.0, incl. whole-number pushes
TOTAL_LINES = [x / 2 for x in range(0, 41)]          # 0.0 .. 20.0
TEAM_LINES = [x / 2 for x in range(0, 25)]           # 0.0 .. 12.0


def _cases():
    yield "MONEYLINE", "HOME", 0.0, None
    yield "MONEYLINE", "AWAY", 0.0, None
    yield "MONEYLINE", "HOME_ML", 0.0, None
    yield "MONEYLINE", "AWAY_ML", 0.0, None
    for line in RL_LINES:
        for side in ("HOME", "AWAY", "HOME_RL", "AWAY_RL"):
            yield "RUN_LINE", side, line, None
    for line in TOTAL_LINES:
        for side in ("OVER", "UNDER"):
            yield "TOTALS", side, line, None
    for line in TEAM_LINES:
        for side in ("OVER", "UNDER"):
            for team in ("HOME", "AWAY"):
                yield "TEAM_TOTALS", side, line, team


def _random_pmf(seed):
    rng = random.Random(seed)
    raw = {f"{a},{h}": rng.random() ** 3 for a in range(13) for h in range(13) if rng.random() < 0.7}
    total = sum(raw.values())
    pmf = {k: v / total for k, v in raw.items()}
    # renormalize residual onto one state so the PMF conserves to < 1e-9
    k0 = next(iter(pmf))
    pmf[k0] += 1.0 - sum(pmf.values())
    return pmf


def _sim_pmf(away, home, sims):
    a, h = v7.calibrated_full_game_means(away, home)
    return v7.simulate_game_distribution(
        away_mean_runs=a, home_mean_runs=h, total_line=8.5, simulations=sims,
        build_hash=hashlib.sha256(f"{away}:{home}:{sims}".encode()).hexdigest(), shared_game_sigma=0.0,
        team_sigma=0.0, team_dispersion_r=v7.V8_INDEPENDENT_TEAM_DISPERSION_R,
        first_inning_share=v7.DEFAULT_FIRST_INNING_SHARE,
        first_inning_dispersion_r=v7.DEFAULT_FIRST_INNING_DISPERSION_R,
        extra_half_inning_mean=v7.V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN,
    ).joint_score_pmf


PMFS = ([("random", s, _random_pmf(s)) for s in range(6)]
        + [("sim", (a, h), _sim_pmf(a, h, 3000))
           for a, h in [(4.1, 4.6), (3.2, 5.4), (5.8, 2.9), (4.5, 4.5)]])


@pytest.mark.parametrize("label,ident,pmf", PMFS, ids=[f"{l}-{i}" for l, i, _ in PMFS])
def test_shared_readout_is_bit_identical_to_removed_engine_arithmetic(label, ident, pmf):
    dist = {"joint_score_pmf": pmf, "result_sha256": "0" * 64}
    n = pushes = 0
    for market, side, line, team in _cases():
        want = _legacy_settle(pmf, market, side, line, team)
        got = read_game_probability(dist, market=market, side=side,
                                    line=None if market == "MONEYLINE" else line,
                                    team_side=team)
        assert (got.probability, got.push_probability) == want, (market, side, line, team)
        n += 1
        pushes += want[1] > 0
    assert n == 4 + 25 * 4 + 41 * 2 + 25 * 4
    assert pushes > 0  # whole-number lines produced real push mass


ADAPTER_CASES = (
    [("MONEYLINE", s, 0.0, None) for s in ("HOME", "AWAY")]
    + [("RUN_LINE", s, l, None) for l in (-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5)
       for s in ("HOME", "AWAY")]
    + [("TOTALS", s, l, None) for l in (6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 11.5)
       for s in ("OVER", "UNDER")]
    + [("TEAM_TOTALS", s, l, t) for l in (2.5, 3.0, 3.5, 4.0, 4.5, 5.0)
       for s in ("OVER", "UNDER") for t in ("HOME", "AWAY")]
)


@pytest.mark.parametrize("market,side,line,team", ADAPTER_CASES)
def test_engine_output_matches_legacy_settlement_end_to_end(monkeypatch, market, side, line, team):
    seen = {}
    real = v7.simulate_game_distribution

    def spy(**kw):
        seen["result"] = real(**kw)
        return seen["result"]

    monkeypatch.setattr(v7, "simulate_game_distribution", spy)
    mi = {"game_id": "g-parity", "entity_id": "game", "market": market, "side": side,
          "line": line, "away_mean_runs": 4.1, "home_mean_runs": 4.6,
          "total_line": 8.5, "simulations": 3000}
    if team:
        mi["team_side"] = team
    out = ge.generic_market_engine_adapter(mi)
    result = seen["result"]
    p, push = _legacy_settle(result.joint_score_pmf, market, side, line, team)
    want = ge._base_output(mi, p, model_hash=result.result_sha256)
    assert out["model_p"] == want["model_p"]
    assert out["push_p"] == push
    for key in ("model_hash", "source_hash"):
        if key in want:
            assert out[key] == want[key]


@pytest.mark.parametrize("mi,msg", [
    ({"market": "MONEYLINE", "side": "OVER"}, "moneyline side must be HOME or AWAY"),
    ({"market": "RUN_LINE", "side": "OVER", "line": -1.5}, "run-line side must be HOME or AWAY"),
    ({"market": "TOTALS", "side": "HOME", "line": 8.5}, "totals side must be OVER or UNDER"),
    ({"market": "TEAM_TOTALS", "side": "OVER", "line": 4.5}, "team_side must be HOME or AWAY"),
    ({"market": "TEAM_TOTALS", "side": "HOME", "line": 4.5, "team_side": "HOME"},
     "team-total side must be OVER or UNDER"),
    ({"market": "TEAM_TOTALS", "side": "OVER", "line": -0.5, "team_side": "HOME"},
     "team-total line must be >= 0"),
])
def test_engine_errors_stay_engine_errors(mi, msg):
    base = {"game_id": "g", "entity_id": "game", "away_mean_runs": 4.0,
            "home_mean_runs": 4.0, "total_line": 8.5, "simulations": 1000}
    with pytest.raises(ge.GenericMarketEngineError, match=msg):
        ge.generic_market_engine_adapter({**base, **mi})
