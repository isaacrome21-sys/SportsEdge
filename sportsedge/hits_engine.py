"""Validated SportsEdge hitter-hits Monte Carlo engine.

Production parameters are frozen from 2021-2022 training data. Sportsbook
prices/probabilities are forbidden from Model_Input. The shared game effect and
candidate-identity RNG are imported production modules, never reimplemented.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Dict

import numpy as np

from .identity_rng import candidate_numpy_rng
from .shared_game_effect import SIGMA_GAME_EFFECT, apply_shared_game_effect

ENGINE_VERSION = "hits_engine_v1.2"
N_MC_PATHS = 2000
FROZEN_MEAN_MODEL_COEF = (
    -0.05944065851222977,
    0.7005549681935409,
    0.5525964280651442,
)
MEAN_MODEL_COEF = FROZEN_MEAN_MODEL_COEF
REQUIRED_FEATURES = ("b_rate", "p_rate", "pa_pool")
BANNED_FEATURE_PATTERNS = (
    "market_prob", "novig", "implied_prob", "dk_prob", "sportsbook_prob",
    "consensus_prob", "closing_prob",
)


class HitsEngineError(ValueError):
    pass


@dataclass(frozen=True)
class HitsModelOutput:
    engine_version: str
    model_input_hash: str
    seed_policy: str
    shared_effect_module_sigma: float
    mc_paths: int
    lineup_status: str
    probs: Dict[float, float]


def _finite_probability(name: str, value) -> float:
    if isinstance(value, bool):
        raise HitsEngineError(f"invalid feature value {name}={value!r}")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise HitsEngineError(f"invalid feature value {name}={value!r}") from exc
    if not isfinite(v) or not 0.0 <= v <= 1.0:
        raise HitsEngineError(f"invalid feature value {name}={value!r}")
    return v


def _validate_pa_pool(pa_pool) -> np.ndarray:
    if not isinstance(pa_pool, (list, tuple, np.ndarray)) or len(pa_pool) == 0:
        raise HitsEngineError("pa_pool must be a non-empty sequence")
    vals = np.asarray(pa_pool, dtype=float)
    if vals.ndim != 1 or not np.all(np.isfinite(vals)):
        raise HitsEngineError("pa_pool must contain finite values")
    # Zero-PA starts exist in the validated historical fixture (e.g. a starter
    # removed before recording a PA), so 0 is legitimate workload history.
    if np.any(vals < 0) or np.any(vals > 9) or np.any(vals != np.floor(vals)):
        raise HitsEngineError("pa_pool must contain integer PA counts in [0,9]")
    return vals.astype(np.int64)


def _validate(model_input: dict) -> tuple[float, float, np.ndarray]:
    if not isinstance(model_input, dict):
        raise HitsEngineError("model_input must be a dict")
    if not model_input.get("build_hash"):
        raise HitsEngineError("missing build_hash")
    if model_input.get("market") != "hits":
        raise HitsEngineError(f"wrong market for hits engine: {model_input.get('market')}")
    feats = model_input.get("features")
    if not isinstance(feats, dict):
        raise HitsEngineError("features must be a dict")
    for feat_name in feats:
        low = str(feat_name).lower()
        for pattern in BANNED_FEATURE_PATTERNS:
            if pattern in low:
                raise HitsEngineError(
                    f"feature '{feat_name}' matches banned sportsbook-probability pattern '{pattern}'"
                )
    for name in REQUIRED_FEATURES:
        if name not in feats:
            raise HitsEngineError(f"missing required feature: {name}")
    b_rate = _finite_probability("b_rate", feats["b_rate"])
    p_rate = _finite_probability("p_rate", feats["p_rate"])
    pa_pool = _validate_pa_pool(feats["pa_pool"])
    lineup_status = model_input.get("lineup_status")
    if lineup_status not in ("CONFIRMED", "PROJECTED"):
        raise HitsEngineError(f"invalid/missing lineup_status: {lineup_status}")
    require_confirmed = model_input.get("require_confirmed_lineup", False)
    if require_confirmed is not True and require_confirmed is not False:
        raise HitsEngineError("require_confirmed_lineup must be boolean")
    if require_confirmed and lineup_status != "CONFIRMED":
        raise HitsEngineError("confirmed lineup required but status is PROJECTED")
    return b_rate, p_rate, pa_pool


def set_frozen_mean_model(coef) -> None:
    """Validation/test hook. Production starts with the frozen train-only fit."""
    global MEAN_MODEL_COEF
    if not isinstance(coef, (tuple, list)) or len(coef) != 3:
        raise HitsEngineError("mean model coefficients must have length 3")
    vals = tuple(float(x) for x in coef)
    if not all(isfinite(x) for x in vals):
        raise HitsEngineError("mean model coefficients must be finite")
    MEAN_MODEL_COEF = vals


def reset_frozen_mean_model() -> None:
    global MEAN_MODEL_COEF
    MEAN_MODEL_COEF = FROZEN_MEAN_MODEL_COEF


def simulate_hits(model_input: dict, thresholds=(0.5, 1.5, 2.5), n_sim: int = N_MC_PATHS) -> HitsModelOutput:
    b_rate, p_rate, pa_pool = _validate(model_input)
    if isinstance(n_sim, bool) or not isinstance(n_sim, int) or n_sim <= 0:
        raise HitsEngineError("n_sim must be a positive integer")
    clean_thresholds = []
    for threshold in thresholds:
        try:
            t = float(threshold)
        except (TypeError, ValueError) as exc:
            raise HitsEngineError(f"invalid threshold: {threshold!r}") from exc
        if not isfinite(t) or t < 0:
            raise HitsEngineError(f"invalid threshold: {threshold!r}")
        clean_thresholds.append(t)

    rng = candidate_numpy_rng(model_input["build_hash"])
    c0, c1, c2 = MEAN_MODEL_COEF
    p = float(np.clip(c0 + c1 * b_rate + c2 * p_rate, 0.02, 0.60))
    draws_pa = rng.choice(pa_pool, size=n_sim, replace=True)
    path_p = apply_shared_game_effect(np.array([p]), n_sim, rng)
    hits = rng.binomial(draws_pa, path_p)
    probs = {t: float((hits > t).mean()) for t in clean_thresholds}
    return HitsModelOutput(
        engine_version=ENGINE_VERSION,
        model_input_hash=model_input["build_hash"],
        seed_policy="identity_sha256_seedsequence_256bit",
        shared_effect_module_sigma=SIGMA_GAME_EFFECT,
        mc_paths=n_sim,
        lineup_status=model_input["lineup_status"],
        probs=probs,
    )
