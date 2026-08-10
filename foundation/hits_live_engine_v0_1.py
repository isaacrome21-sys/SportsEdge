#!/usr/bin/env python3
"""SportsEdge hitter-hits live engine v0.1.

Faithful production wiring of the validated shared-game-effect Hits mechanism.
Uses frozen 2021-2022 train-fit mean coefficients, exact empirical train PA
multiset counts, reusable candidate-identity RNG, and the packaged shared game
effect module. Deployment capability must remain false until CI/full-fixture
attestation is completed.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
import numpy as np

from sportsedge_identity_rng import candidate_rng, SEED_POLICY
from sportsedge_shared_game_effect import (
    SIGMA_GAME_EFFECT,
    CODE_VERSION as SHARED_EFFECT_CODE_VERSION,
    apply_shared_game_effect,
)

ENGINE_VERSION = "hits_live_v0.1"
ORIGIN_FIXTURE_SHA256 = "8c15e196efa5fc7ef979d0a9cf5ec113cba54cd756482babc256c44d53642409"
DEFAULT_PATHS = 2_000
SHRINKAGE = 5
MEAN_MODEL_COEF = (-0.05944066, 0.70055497, 0.55259643)
TRAIN_PA_COUNTS = {1: 883, 2: 3219, 3: 11715, 4: 44291, 5: 17737, 6: 1290, 7: 38}
TRAIN_PA_POOL_SIZE = 79_173
SUPPORTED_LINES = (0.5, 1.5, 2.5)
EXPECTED_FEATURES = ("b_rate", "p_rate", "pa_pool")


class HitsEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class HitsModelOutput:
    engine_version: str
    model_input_hash: str
    seed_policy: str
    shared_effect_code_version: str
    shared_effect_sigma: float
    mc_paths: int
    lineup_status: str
    probs: Dict[float, float]


def _baseline_pa_pool() -> np.ndarray:
    arr = np.concatenate([
        np.full(count, pa, dtype=np.int16)
        for pa, count in sorted(TRAIN_PA_COUNTS.items())
    ])
    if len(arr) != TRAIN_PA_POOL_SIZE:
        raise HitsEngineError("BASELINE_PA_POOL_SIZE_MISMATCH")
    return arr


def _validate(model_input: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(model_input, dict):
        raise HitsEngineError("MODEL_INPUT_NOT_DICT")
    if model_input.get("market") != "hits":
        raise HitsEngineError("WRONG_MARKET")
    build_hash = model_input.get("build_hash")
    if not isinstance(build_hash, str) or not build_hash:
        raise HitsEngineError("MODEL_INPUT_HASH_MISSING")
    if model_input.get("lineup_status") != "CONFIRMED":
        raise HitsEngineError("LINEUP_NOT_CONFIRMED")
    f = model_input.get("features")
    if not isinstance(f, dict) or set(f) != set(EXPECTED_FEATURES):
        raise HitsEngineError("FEATURE_CONTRACT_MISMATCH")
    for key in ("b_rate", "p_rate"):
        value = f[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 <= float(value) <= 1:
            raise HitsEngineError(f"INVALID_FEATURE:{key}")
    pool = f["pa_pool"]
    if not isinstance(pool, (list, tuple)) or not pool:
        raise HitsEngineError("INVALID_FEATURE:pa_pool")
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in pool):
        raise HitsEngineError("INVALID_FEATURE:pa_pool")
    if SIGMA_GAME_EFFECT != 0.20 or SHARED_EFFECT_CODE_VERSION != "shared_game_effect_v1.0":
        raise HitsEngineError("SHARED_EFFECT_MODULE_PARITY_MISMATCH")
    return f


def simulate_hits(model_input: Dict[str, Any], *, thresholds=SUPPORTED_LINES,
                  n_paths: int = DEFAULT_PATHS) -> HitsModelOutput:
    f = _validate(model_input)
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths < 1:
        raise HitsEngineError("INVALID_PATH_COUNT")
    thresholds = tuple(float(t) for t in thresholds)
    if any(t not in SUPPORTED_LINES for t in thresholds):
        raise HitsEngineError("UNSUPPORTED_LINE")

    rng = candidate_rng(model_input["build_hash"])
    own_pool = np.asarray(f["pa_pool"], dtype=np.int16)
    baseline = _baseline_pa_pool()
    weight = len(own_pool) / (len(own_pool) + SHRINKAGE)
    use_own = rng.random(n_paths) < weight
    draws = np.empty(n_paths, dtype=np.int16)
    n_own = int(use_own.sum())
    if n_own:
        draws[use_own] = rng.choice(own_pool, size=n_own, replace=True)
    if n_paths - n_own:
        draws[~use_own] = rng.choice(baseline, size=n_paths - n_own, replace=True)

    c0, c1, c2 = MEAN_MODEL_COEF
    p = float(np.clip(c0 + c1 * float(f["b_rate"]) + c2 * float(f["p_rate"]), 0.02, 0.60))
    ps = apply_shared_game_effect(np.array([p]), n_paths, rng)
    hits = rng.binomial(draws, ps)
    probs = {t: float(np.mean(hits > t)) for t in thresholds}

    return HitsModelOutput(
        engine_version=ENGINE_VERSION,
        model_input_hash=model_input["build_hash"],
        seed_policy=SEED_POLICY,
        shared_effect_code_version=SHARED_EFFECT_CODE_VERSION,
        shared_effect_sigma=SIGMA_GAME_EFFECT,
        mc_paths=n_paths,
        lineup_status=model_input["lineup_status"],
        probs=probs,
    )
