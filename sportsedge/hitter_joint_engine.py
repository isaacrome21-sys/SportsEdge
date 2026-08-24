"""Coherent PA-level hitter market challenger.

One simulated/analytic PA state drives all hitter counting markets so overlapping
propositions cannot disagree by construction. This is candidate runtime code;
behavioral promotion remains a separate evidence decision.
"""
from __future__ import annotations

import hashlib
import json
from math import comb, floor, isfinite
from typing import Any, Mapping

ENGINE_VERSION = "mlb_hitter_joint_pa_v1"

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


def _binom_pmf(n: int, p: float) -> list[float]:
    return [comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k)) for k in range(n + 1)]


def _convolve(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def _event_pmf(n: int, p: float, weight: int = 1) -> list[float]:
    base = _binom_pmf(n, p)
    if weight == 1:
        return base
    out = [0.0] * (n * weight + 1)
    for k, q in enumerate(base):
        out[k * weight] = q
    return out


def _market_pmf(features: Mapping[str, Any], market: str) -> tuple[list[float], dict[str, Any]]:
    pa_proj = _f(features.get("projected_pa"), "projected_pa", 0.0)
    n = floor(pa_proj + 0.5)
    if n < 1:
        raise HitterJointEngineError("projected_pa rounds to n < 1")

    # Mutually exclusive batting-result probabilities per PA.
    p1 = _f(features.get("p_single", 0.0), "p_single", 0.0, 1.0)
    p2 = _f(features.get("p_double", 0.0), "p_double", 0.0, 1.0)
    p3 = _f(features.get("p_triple", 0.0), "p_triple", 0.0, 1.0)
    phr = _f(features.get("p_hr", 0.0), "p_hr", 0.0, 1.0)
    pbb = _f(features.get("p_bb", 0.0), "p_bb", 0.0, 1.0)
    if p1 + p2 + p3 + phr + pbb > 1.0 + 1e-12:
        raise HitterJointEngineError("PA event probabilities exceed 1")

    phit = p1 + p2 + p3 + phr
    pxbh = p2 + p3 + phr
    prun = _f(features.get("p_run_per_pa", 0.0), "p_run_per_pa", 0.0, 1.0)
    prbi = _f(features.get("p_rbi_per_pa", 0.0), "p_rbi_per_pa", 0.0, 1.0)
    psb = _f(features.get("p_sb_per_pa", 0.0), "p_sb_per_pa", 0.0, 1.0)

    one_dim = {
        "HITS": _event_pmf(n, phit),
        "HOME_RUNS": _event_pmf(n, phr),
        "RBI": _event_pmf(n, prbi),
        "RUNS": _event_pmf(n, prun),
        "STOLEN_BASES": _event_pmf(n, psb),
        "BATTER_BB": _event_pmf(n, pbb),
        "EXTRA_BASE_HITS": _event_pmf(n, pxbh),
    }
    if market in one_dim:
        return one_dim[market], {"n": n, "p_hit": phit, "p_xbh": pxbh}

    if market == "TOTAL_BASES":
        # Exact single-PA TB support {0,1,2,3,4}, repeated n times.
        pa = [max(0.0, 1.0 - phit), p1, p2, p3, phr]
        pmf = [1.0]
        for _ in range(n):
            pmf = _convolve(pmf, pa)
        return pmf, {"n": n, "p_hit": phit, "p_xbh": pxbh}

    # Combo markets are derived from the same component marginals. These preserve
    # arithmetic identity but do not yet encode within-PA dependence among run/RBI/SB.
    pieces: list[list[float]] = []
    if market == "HITS_RUNS_RBIS":
        pieces = [one_dim["HITS"], one_dim["RUNS"], one_dim["RBI"]]
    elif market == "HITS_RUNS_STOLEN_BASES":
        pieces = [one_dim["HITS"], one_dim["RUNS"], one_dim["STOLEN_BASES"]]
    elif market == "RUNS_RBIS":
        pieces = [one_dim["RUNS"], one_dim["RBI"]]
    elif market == "HITS_STOLEN_BASES":
        pieces = [one_dim["HITS"], one_dim["STOLEN_BASES"]]
    elif market == "HITS_WALKS_STOLEN_BASES":
        pieces = [one_dim["HITS"], one_dim["BATTER_BB"], one_dim["STOLEN_BASES"]]
    else:
        raise HitterJointEngineError(f"unsupported hitter market {market}")
    pmf = [1.0]
    for piece in pieces:
        pmf = _convolve(pmf, piece)
    return pmf, {"n": n, "p_hit": phit, "p_xbh": pxbh, "combo_dependence": "INDEPENDENT_COMPONENT_V1"}


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
        "engine": ENGINE_VERSION, "market": market, "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"), "feature_source_hash": model_input.get("feature_source_hash"),
        "features": dict(features),
    })
    return {
        "game_id": model_input.get("game_id"), "market": market, "entity_id": model_input.get("entity_id"),
        "line": line, "side": side, "model_p": p_over if side == "OVER" else p_under,
        "push_p": p_push, "model_input_hash": digest, "engine_version": ENGINE_VERSION,
        "seed_policy": "analytic_shared_pa_state", "mc_paths": 0, "meta": meta,
    }
