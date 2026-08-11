"""Validated pitcher-walks Monte Carlo engine with rolling recalibration."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Dict

import numpy as np

from .identity_rng import candidate_numpy_rng
from .rolling_recal import recalibrated_rate, SHRINKAGE, WINDOW_DAYS

ENGINE_VERSION = "bb_engine_v1.0"
FEATURE_CONTRACT_VERSION = "pitcher_bb_features_v1"
N_MC_PATHS = 2000
WORKLOAD_SHRINK = 5


class BBEngineError(ValueError):
    pass


@dataclass(frozen=True)
class BBModelOutput:
    engine_version: str
    model_input_hash: str
    window_days: int
    shrinkage: int
    runtime_capability_attested: bool
    mc_paths: int
    probs: Dict[float, float]


def _finite(name, value, lo=None, hi=None) -> float:
    if isinstance(value, bool):
        raise BBEngineError(f"invalid {name}")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise BBEngineError(f"invalid {name}") from exc
    if not isfinite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise BBEngineError(f"invalid {name}")
    return v


def _pool(name, value) -> np.ndarray:
    if not isinstance(value, (list, tuple, np.ndarray)) or len(value) == 0:
        raise BBEngineError(f"{name} must be non-empty")
    a = np.asarray(value, dtype=float)
    if a.ndim != 1 or not np.all(np.isfinite(a)) or np.any(a < 0) or np.any(a != np.floor(a)):
        raise BBEngineError(f"{name} must contain non-negative integer workloads")
    return a.astype(np.int64)


def _validate(model_input: dict):
    if not isinstance(model_input, dict):
        raise BBEngineError("model_input must be a dict")
    if not model_input.get("build_hash"):
        raise BBEngineError("missing build_hash")
    if model_input.get("market") != "pitcher_walks":
        raise BBEngineError("wrong market for BB engine")
    f = model_input.get("features")
    if not isinstance(f, dict):
        raise BBEngineError("features must be a dict")
    expected = {"own_bb", "own_bfp", "rolling_league_rate", "pool", "league_pool"}
    if set(f) != expected:
        raise BBEngineError(f"features must contain exactly {sorted(expected)}")
    own_bb = _finite("own_bb", f["own_bb"], 0)
    own_bfp = _finite("own_bfp", f["own_bfp"], 1)
    if own_bb > own_bfp:
        raise BBEngineError("own_bb cannot exceed own_bfp")
    rolling = _finite("rolling_league_rate", f["rolling_league_rate"], 0.001, 0.5)
    return own_bb, own_bfp, rolling, _pool("pool", f["pool"]), _pool("league_pool", f["league_pool"])


def simulate_bb(model_input: dict, thresholds=(0.5, 1.5, 2.5, 3.5), n_sim: int = N_MC_PATHS) -> BBModelOutput:
    own_bb, own_bfp, rolling, own_pool, league_pool = _validate(model_input)
    if isinstance(n_sim, bool) or not isinstance(n_sim, int) or n_sim <= 0:
        raise BBEngineError("n_sim must be a positive integer")
    clean = [_finite("threshold", x, 0) for x in thresholds]
    rate = recalibrated_rate(int(own_bb), int(own_bfp), rolling, shrinkage=SHRINKAGE)
    rng = candidate_numpy_rng(model_input["build_hash"])
    w_own = len(own_pool) / (len(own_pool) + WORKLOAD_SHRINK)
    use_own = rng.random(n_sim) < w_own
    draws = np.empty(n_sim, dtype=np.int64)
    n_own = int(use_own.sum())
    if n_own:
        draws[use_own] = rng.choice(own_pool, size=n_own, replace=True)
    if n_sim - n_own:
        draws[~use_own] = rng.choice(league_pool, size=n_sim - n_own, replace=True)
    walks = rng.binomial(draws, rate)
    probs = {t: float((walks > t).mean()) for t in clean}
    return BBModelOutput(ENGINE_VERSION, model_input["build_hash"], WINDOW_DAYS, SHRINKAGE, True, n_sim, probs)
