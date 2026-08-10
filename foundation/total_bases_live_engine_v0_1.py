#!/usr/bin/env python3
"""SportsEdge total-bases live engine v0.1.

Reference wiring for the validated TB shared-game-effect path. This module is
intentionally narrow: it prices only the validated 0.5/1.5/2.5 thresholds,
uses the train-only constants recovered from the accepted TB fixture, and calls
sportsedge_shared_game_effect.sample_game_effect instead of reimplementing the
lognormal sampler inline.

Runtime capability must remain false until this exact path passes independent
acceptance against the full holdout fixture.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional, Tuple
import numpy as np

from sportsedge_shared_game_effect import (
    CODE_VERSION as SHARED_EFFECT_CODE_VERSION,
    SIGMA_GAME_EFFECT,
    sample_game_effect,
)

CODE_VERSION = "total_bases_live_v0.1"
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
SEED_POLICY = "sha256_build_hash_seedsequence_v1"

# Exact empirical value counts from the accepted 2021-2022 train_pa_pool.
# Reconstructing the multiset from counts preserves the sampling distribution.
# It does NOT claim byte/path identity with the original pickle order; that is
# why full acceptance remains required before capability attestation can flip.
TRAIN_PA_COUNTS = {1: 175, 2: 1313, 3: 7220, 4: 30924, 5: 12676, 6: 868, 7: 29}
TRAIN_PA_POOL_SIZE = 53_205

EXPECTED_FEATURES = (
    "rates_s", "rates_d", "rates_t", "rates_hr",
    "p_h", "p_hr", "park", "pa_pool",
)


class TotalBasesEngineError(RuntimeError):
    pass


def _baseline_pa_pool() -> np.ndarray:
    arr = np.concatenate([
        np.full(count, pa, dtype=np.int16)
        for pa, count in sorted(TRAIN_PA_COUNTS.items())
    ])
    if len(arr) != TRAIN_PA_POOL_SIZE:
        raise TotalBasesEngineError("BASELINE_PA_POOL_SIZE_MISMATCH")
    return arr


def _seed_sequence_from_build_hash(build_hash: str) -> Tuple[np.random.SeedSequence, str]:
    """Map immutable candidate identity to a deterministic, well-spread PRNG seed.

    The complete SHA-256 digest of the build_hash string is split into eight
    independent 32-bit entropy words and fed to NumPy SeedSequence. No row
    number, batch position, wall clock, or low-order-bit truncation participates.
    """
    digest = hashlib.sha256(build_hash.encode("utf-8")).digest()
    entropy_words = [int.from_bytes(digest[i:i + 4], "big") for i in range(0, 32, 4)]
    return np.random.SeedSequence(entropy_words), digest.hex()


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
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    f = _validate_input(model_input)
    if float(line) not in SUPPORTED_LINES:
        raise TotalBasesEngineError("UNSUPPORTED_LINE")
    if side not in {"over", "under"}:
        raise TotalBasesEngineError("UNSUPPORTED_SIDE")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths < 1:
        raise TotalBasesEngineError("INVALID_PATH_COUNT")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise TotalBasesEngineError("INVALID_SEED")

    if seed is None:
        seed_material, seed_fingerprint = _seed_sequence_from_build_hash(model_input["build_hash"])
        seed_policy = SEED_POLICY
    else:
        seed_material = seed
        seed_fingerprint = hashlib.sha256(f"explicit:{seed}".encode("utf-8")).hexdigest()
        seed_policy = "explicit_integer_seed_research_only"

    rng = np.random.default_rng(seed_material)
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

    # Critical deployment-parity call: shared effect comes from the packaged
    # production module, not an inline lognormal reimplementation.
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
        "model_input_hash": model_input["build_hash"],
        "source_kind": "SPORTSEDGE_MC",
        "engine_code_version": CODE_VERSION,
        "shared_game_effect_code_version": SHARED_EFFECT_CODE_VERSION,
        "shared_game_effect_sigma": SIGMA_GAME_EFFECT,
        "origin_fixture_sha256": ORIGIN_FIXTURE_SHA256,
        "mc_status": "PASS",
        "mc_paths": n_paths,
        "seed_policy": seed_policy,
        "seed_fingerprint": seed_fingerprint,
        "line": float(line),
        "side": side,
    }
