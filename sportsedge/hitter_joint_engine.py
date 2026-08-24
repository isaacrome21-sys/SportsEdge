"""Coherent PA-level hitter market challenger.

Every hitter market is derived from one per-PA state model and repeated across a
fixed PIT projected-PA count. Overlapping propositions therefore share the same
latent batting result instead of being independently parameterized engines.

This is candidate runtime code; promotion still requires behavioral evidence.
"""
from __future__ import annotations

import hashlib
import json
from math import floor, isfinite
from typing import Any, Mapping

ENGINE_VERSION = "mlb_hitter_joint_pa_v2"

HITTER_MARKETS = frozenset({
    "HITS", "HOME_RUNS", "TOTAL_BASES", "RBI", "RUNS", "STOLEN_BASES", "BATTER_BB",
    "EXTRA_BASE_HITS", "HITS_RUNS_RBIS", "HITS_RUNS_STOLEN_BASES", "RUNS_RBIS",
    "HITS_STOLEN_BASES", "HITS_WALKS_STOLEN_BASES",
})

class HitterJointEngineError(ValueError):
    pass


def _f(v: Any, name: str, lo: float = 0.0, hi: float | None = None) -> float:
    if isinstance(v, bool):
        raise HitterJointEngineError(f"{name} must be numeric")
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise HitterJointEngineError(f"{name} must be numeric") from exc
    if not isfinite(x) or x < lo or (hi is not None and x > hi):
        raise HitterJointEngineError(f"{name} out of bounds")
    return x


def _sha(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _convolve(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def _repeat_pa(single_pa: list[float], n: int) -> list[float]:
    pmf = [1.0]
    for _ in range(n):
        pmf = _convolve(pmf, single_pa)
    return pmf


def _bernoulli_states(p: float) -> tuple[tuple[int, float], tuple[int, float]]:
    return ((0, 1.0 - p), (1, p))


def _market_pmf(features: Mapping[str, Any], market: str) -> tuple[list[float], dict[str, Any]]:
    pa_proj = _f(features.get("projected_pa"), "projected_pa", 0.0)
    n = floor(pa_proj + 0.5)
    if n < 1:
        raise HitterJointEngineError("projected_pa rounds to n < 1")

    # One mutually-exclusive batting-result state per PA.
    p1 = _f(features.get("p_single", 0.0), "p_single", 0.0, 1.0)
    p2 = _f(features.get("p_double", 0.0), "p_double", 0.0, 1.0)
    p3 = _f(features.get("p_triple", 0.0), "p_triple", 0.0, 1.0)
    phr = _f(features.get("p_hr", 0.0), "p_hr", 0.0, 1.0)
    pbb = _f(features.get("p_bb", 0.0), "p_bb", 0.0, 1.0)
    p_batted = p1 + p2 + p3 + phr + pbb
    if p_batted > 1.0 + 1e-12:
        raise HitterJointEngineError("PA event probabilities exceed 1")
    pout = max(0.0, 1.0 - p_batted)

    # Run/RBI/SB are additional same-PA outcomes in v2. They are not separate
    # game-level engines. Their conditional structure is intentionally explicit:
    # until richer base/out state is available, each is conditionally independent
    # given the shared batting-result state, using PIT per-PA probabilities.
    prun = _f(features.get("p_run_per_pa", 0.0), "p_run_per_pa", 0.0, 1.0)
    prbi = _f(features.get("p_rbi_per_pa", 0.0), "p_rbi_per_pa", 0.0, 1.0)
    psb = _f(features.get("p_sb_per_pa", 0.0), "p_sb_per_pa", 0.0, 1.0)

    batting_states = (
        {"hit": 0, "hr": 0, "tb": 0, "bb": 0, "xbh": 0, "p": pout},
        {"hit": 1, "hr": 0, "tb": 1, "bb": 0, "xbh": 0, "p": p1},
        {"hit": 1, "hr": 0, "tb": 2, "bb": 0, "xbh": 1, "p": p2},
        {"hit": 1, "hr": 0, "tb": 3, "bb": 0, "xbh": 1, "p": p3},
        {"hit": 1, "hr": 1, "tb": 4, "bb": 0, "xbh": 1, "p": phr},
        {"hit": 0, "hr": 0, "tb": 0, "bb": 1, "xbh": 0, "p": pbb},
    )

    max_single = {
        "HITS": 1, "HOME_RUNS": 1, "TOTAL_BASES": 4, "RBI": 1,
        "RUNS": 1, "STOLEN_BASES": 1, "BATTER_BB": 1, "EXTRA_BASE_HITS": 1,
        "HITS_RUNS_RBIS": 3, "HITS_RUNS_STOLEN_BASES": 3, "RUNS_RBIS": 2,
        "HITS_STOLEN_BASES": 2, "HITS_WALKS_STOLEN_BASES": 3,
    }[market]
    single = [0.0] * (max_single + 1)

    for b in batting_states:
        if b["p"] <= 0:
            continue
        for run, pr in _bernoulli_states(prun):
            for rbi, pi in _bernoulli_states(prbi):
                for sb, ps in _bernoulli_states(psb):
                    prob = b["p"] * pr * pi * ps
                    if market == "HITS": value = b["hit"]
                    elif market == "HOME_RUNS": value = b["hr"]
                    elif market == "TOTAL_BASES": value = b["tb"]
                    elif market == "RBI": value = rbi
                    elif market == "RUNS": value = run
                    elif market == "STOLEN_BASES": value = sb
                    elif market == "BATTER_BB": value = b["bb"]
                    elif market == "EXTRA_BASE_HITS": value = b["xbh"]
                    elif market == "HITS_RUNS_RBIS": value = b["hit"] + run + rbi
                    elif market == "HITS_RUNS_STOLEN_BASES": value = b["hit"] + run + sb
                    elif market == "RUNS_RBIS": value = run + rbi
                    elif market == "HITS_STOLEN_BASES": value = b["hit"] + sb
                    elif market == "HITS_WALKS_STOLEN_BASES": value = b["hit"] + b["bb"] + sb
                    else: raise HitterJointEngineError(f"unsupported hitter market {market}")
                    single[value] += prob

    if abs(sum(single) - 1.0) > 1e-10:
        raise HitterJointEngineError("single-PA probability mass does not conserve")
    pmf = _repeat_pa(single, n)
    return pmf, {
        "n": n,
        "shared_pa_state": True,
        "p_hit": p1 + p2 + p3 + phr,
        "p_xbh": p2 + p3 + phr,
        "conditional_structure": "RUN_RBI_SB_INDEPENDENT_GIVEN_BATTING_STATE_V1",
    }


def price_hitter_market(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market", "")).upper()
    if market not in HITTER_MARKETS:
        raise HitterJointEngineError(f"unsupported hitter market {market}")
    side = str(model_input.get("side", "")).upper()
    if side not in {"OVER", "UNDER"}:
        raise HitterJointEngineError("side must be OVER or UNDER")
    line = _f(model_input.get("line"), "line", 0.0)
    features = model_input.get("features")
    if not isinstance(features, Mapping):
        raise HitterJointEngineError("features required")
    pmf, meta = _market_pmf(features, market)
    k = floor(line)
    p_over = sum(pmf[k + 1:]) if k + 1 < len(pmf) else 0.0
    if float(line).is_integer():
        t = int(line)
        p_push = pmf[t] if 0 <= t < len(pmf) else 0.0
        p_under = sum(pmf[:t])
    else:
        p_push = 0.0
        p_under = sum(pmf[: k + 1])
    if abs(p_over + p_under + p_push - 1.0) > 1e-9:
        raise HitterJointEngineError("probability mass does not conserve")
    digest = _sha({
        "engine": ENGINE_VERSION, "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"), "feature_source_hash": model_input.get("feature_source_hash"),
        "features": dict(features),
    })
    return {
        "game_id": model_input.get("game_id"), "market": market, "entity_id": model_input.get("entity_id"),
        "line": line, "side": side, "model_p": p_over if side == "OVER" else p_under,
        "push_p": p_push, "model_input_hash": digest, "engine_version": ENGINE_VERSION,
        "seed_policy": "analytic_shared_pa_state", "mc_paths": 0, "meta": meta,
    }
