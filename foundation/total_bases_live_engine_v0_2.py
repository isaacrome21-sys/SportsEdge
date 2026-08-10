#!/usr/bin/env python3
"""SportsEdge total-bases live engine v0.2.

Reference wiring for the validated TB shared-game-effect path. This version
removes the unsafe fixed-seed-per-candidate behavior from v0.1. Production RNG
entropy is derived deterministically from the immutable Model_Input build_hash:
identical inputs reproduce exactly, while distinct candidates do not reuse the
same random stream.

Runtime capability must remain false until this exact path passes full holdout
acceptance against the frozen TB fixture.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict
import numpy as np

from sportsedge_shared_game_effect import (
    CODE_VERSION as SHARED_EFFECT_CODE_VERSION,
    SIGMA_GAME_EFFECT,
    sample_game_effect,
)

CODE_VERSION = "total_bases_live_v0.2"
SEED_POLICY = "sha256_full_digest_of_model_input_build_hash_v1"
ORIGIN_FIXTURE_SHA256 = "3abd596ae720529f5354f724c02c11e284a5044ac5842207599c27f4cb562e82"
ORIGIN_FIXTURE_ROWS = 126_241
LG_PH = 0.2258
LG_HR = 0.03357
AH = 0.7
AHR = 0.3
KP = 0.5
SCALE_CONSTANT = 0.997832032579663
PA_SHRINKAGE = 5
SUPPORTED_LINES = (0.5, 1.5, 2.5)
DEFAULT_PATHS = 25_000

TRAIN_PA_COUNTS = {1: 175, 2: 1313, 3: 7220, 4: 30924, 5: 12676, 6: 868, 7: 29}
TRAIN_PA_POOL_SIZE = 53_205

EXPECTED_FEATURES = (
    "rates_s", "rates_d", "rates_t", "rates_hr",
    "p_h", "p_hr", "park", "pa_pool",
)


class TotalBasesEngineError(RuntimeError):
    pass


def seed_from_build_hash(build_hash: str) -> int:
    """Map immutable Model_Input identity to 256 bits of SeedSequence entropy."""
    if not isinstance(build_hash, str) or not build_hash:
        raise TotalBasesEngineError("MODEL_INPUT_HASH_MISSING")
    digest = hashlib.sha256(build_hash.encode("utf-8")).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def _baseline_pa_pool() -> np.ndarray:
    arr = np.concatenate([
        np.full(count, pa, dtype=np.int16)
        for pa, count in sorted(TRAIN_PA_COUNTS.items())
    ])
    if len(arr) != TRAIN_PA_POOL_SIZE:
        raise TotalBasesEngineError("BASELINE_PA_POOL_SIZE_MISMATCH")
    return arr


def _validate_input(model_input: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(model_input, dict):
        raise TotalBasesEngineError("MODEL_INPUT_NOT_DICT")
    if model_input.get("market") != "total_bases":
        raise TotalBasesEngineError("WRONG_MARKET")
    if model_input.get("lineup_status") != "CONFIRMED":
        raise TotalBasesEngineError("LINEUP_NOT_CONFIRMED")
    build_hash = model_input.get("build_hash")
    if not isinstance(build_hash, str) or not build_hash:
        raise TotalBasesEngineError("MODEL_INPUT_HASH_MISSING")
    f = model_input.get("features")
    if not isinstance(f, dict) or set(f) != set(EXPECTED_FEATURES):
        raise TotalBasesEngineError("FEATURE_CONTRACT_MISMATCH")
    for k in ("rates_s", "rates_d", "rates_t", "rates_hr", "p_h", "p_hr"):
        v = f[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or not 0 <= float(v) <= 1:
            raise TotalBasesEngineError(f"INVALID_FEATURE:{k}")
    park = f["park"]
    if isinstance(park, bool) or not isinstance(park, (int, float)) or not np.isfinite(park) or not 0.25 <= float(park) <= 4.0:
        raise TotalBasesEngineError("INVALID_FEATURE:park")
    pa_pool = f["pa_pool"]
    if not isinstance(pa_pool, (list, tuple)) or not pa_pool:
        raise TotalBasesEngineError("INVALID_FEATURE:pa_pool")
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in pa_pool):
        raise TotalBasesEngineError("INVALID_FEATURE:pa_pool")
    if SIGMA_GAME_EFFECT != 0.20 or SHARED_EFFECT_CODE_VERSION != "shared_game_effect_v1.0":
        raise TotalBasesEngineError("SHARED_EFFECT_MODULE_PARITY_MISMATCH")
    return f


def simulate_total_bases(
    model_input: Dict[str, Any],
    *,
    line: float,
    side: str = "over",
    n_paths: int = DEFAULT_PATHS,
) -> Dict[str, Any]:
    f = _validate_input(model_input)
    if float(line) not in SUPPORTED_LINES:
        raise TotalBasesEngineError("UNSUPPORTED_LINE")
    if side not in {"over", "under"}:
        raise TotalBasesEngineError("UNSUPPORTED_SIDE")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths < 1:
        raise TotalBasesEngineError("INVALID_PATH_COUNT")

    build_hash = model_input["build_hash"]
    seed = seed_from_build_hash(build_hash)
    rng = np.random.default_rng(seed)
    pa_pool = np.asarray(f["pa_pool"], dtype=np.int16)
    baseline = _baseline_pa_pool()

    wt = len(pa_pool) / (len(pa_pool) + PA_SHRINKAGE)
    use_own = rng.random(n_paths) < wt
    draws = np.empty(n_paths, dtype=np.int16)
    n_own = int(use_own.sum())
    if n_own:
        draws[use_own] = rng.choice(pa_pool, size=n_own, replace=True)
    if n_paths - n_own:
        draws[~use_own] = rng.choice(baseline, size=n_paths - n_own, replace=True)

    contact_mult = (float(f["p_h"]) / LG_PH) ** AH
    hr_mult = (float(f["p_hr"]) / LG_HR) ** AHR
    park_mult = float(f["park"]) ** KP
    ps = np.array([
        float(f["rates_s"]) * contact_mult,
        float(f["rates_d"]) * contact_mult,
        float(f["rates_t"]) * contact_mult,
        float(f["rates_hr"]) * hr_mult * park_mult,
    ], dtype=float)
    ps = np.clip(ps * SCALE_CONSTANT, 1e-5, 0.5)

    game_factor = sample_game_effect(n_paths, rng)
    scaled_ps = ps[None, :] * game_factor[:, None]
    cumulative = np.cumsum(scaled_ps, axis=1)

    max_pa = max(9, int(draws.max()) + 2)
    u = rng.random((n_paths, max_pa))
    values = np.zeros((n_paths, max_pa), dtype=np.int8)
    values[u < cumulative[:, 3:4]] = 4
    values[u < cumulative[:, 2:3]] = 3
    values[u < cumulative[:, 1:2]] = 2
    values[u < cumulative[:, 0:1]] = 1
    mask = np.arange(max_pa)[None, :] < draws[:, None]
    tb = (values * mask).sum(axis=1)

    p_over = float(np.mean(tb > float(line)))
    p_under = float(np.mean(tb < float(line)))
    model_p = p_over if side == "over" else p_under
    return {
        "model_p": model_p,
        "p_over": p_over,
        "p_under": p_under,
        "mean": float(np.mean(tb)),
        "variance": float(np.var(tb, ddof=1)) if n_paths > 1 else 0.0,
        "model_input_hash": build_hash,
        "source_kind": "SPORTSEDGE_MC",
        "engine_code_version": CODE_VERSION,
        "shared_game_effect_code_version": SHARED_EFFECT_CODE_VERSION,
        "shared_game_effect_sigma": SIGMA_GAME_EFFECT,
        "origin_fixture_sha256": ORIGIN_FIXTURE_SHA256,
        "mc_status": "PASS",
        "mc_paths": n_paths,
        "seed_policy": SEED_POLICY,
        "seed_fingerprint": hashlib.sha256(build_hash.encode("utf-8")).hexdigest()[:16],
        "line": float(line),
        "side": side,
    }
