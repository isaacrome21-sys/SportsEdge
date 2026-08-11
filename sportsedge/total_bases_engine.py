"""Validated hitter Total Bases Monte Carlo engine.

The Total Bases model intentionally reuses the Hits shared-game-effect sigma
without refitting. All constants below are frozen from 2021-2022 training data.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Dict

import numpy as np

from .identity_rng import candidate_numpy_rng
from .shared_game_effect import SIGMA_GAME_EFFECT, sample_game_effect

ENGINE_VERSION = "total_bases_engine_v0.2"
FEATURE_CONTRACT_VERSION = "tb_event_rates_pitcher_park_pa_v1"
N_MC_PATHS = 2000
LG_P_H = 0.2258
LG_P_HR = 0.03357
BATTER_HIT_EXPONENT = 0.7
PITCHER_HR_EXPONENT = 0.3
PARK_EXPONENT = 0.5
TRAIN_SCALE = 0.997832032579663
WORKLOAD_SHRINK = 5
MAX_PA_SLOTS = 9
# Exact 2021-2022 train PA multiset, represented compactly. Reconstructing it
# in sorted order preserves the empirical distribution; validation confirmed
# multiset identity is what the workload blend requires.
TRAIN_PA_COUNTS = {1: 175, 2: 1313, 3: 7220, 4: 30924, 5: 12676, 6: 868, 7: 29}
TRAIN_PA_POOL = np.repeat(
    np.array(sorted(TRAIN_PA_COUNTS), dtype=np.int64),
    np.array([TRAIN_PA_COUNTS[k] for k in sorted(TRAIN_PA_COUNTS)], dtype=np.int64),
)


class TotalBasesEngineError(ValueError):
    pass


@dataclass(frozen=True)
class TotalBasesModelOutput:
    engine_version: str
    model_input_hash: str
    seed_policy: str
    shared_effect_module_sigma: float
    mc_paths: int
    lineup_status: str
    probs: Dict[float, float]


def _finite(name, value, lo=None, hi=None) -> float:
    if isinstance(value, bool):
        raise TotalBasesEngineError(f"invalid {name}")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise TotalBasesEngineError(f"invalid {name}") from exc
    if not isfinite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise TotalBasesEngineError(f"invalid {name}")
    return v


def _pa_pool(value) -> np.ndarray:
    if not isinstance(value, (list, tuple, np.ndarray)) or len(value) == 0:
        raise TotalBasesEngineError("pa_pool must be a non-empty sequence")
    a = np.asarray(value, dtype=float)
    if a.ndim != 1 or not np.all(np.isfinite(a)) or np.any(a < 0) or np.any(a > MAX_PA_SLOTS) or np.any(a != np.floor(a)):
        raise TotalBasesEngineError("pa_pool must contain integer PA counts in valid range")
    return a.astype(np.int64)


def _validate(model_input: dict):
    if not isinstance(model_input, dict):
        raise TotalBasesEngineError("model_input must be a dict")
    if not model_input.get("build_hash"):
        raise TotalBasesEngineError("missing build_hash")
    if model_input.get("market") != "total_bases":
        raise TotalBasesEngineError("wrong market for Total Bases engine")
    features = model_input.get("features")
    if not isinstance(features, dict):
        raise TotalBasesEngineError("features must be a dict")
    banned = ("market_prob", "novig", "implied_prob", "dk_prob", "sportsbook_prob", "consensus_prob", "closing_prob")
    for key in features:
        low = str(key).lower()
        if any(x in low for x in banned):
            raise TotalBasesEngineError(f"sportsbook probability feature banned: {key}")
    rates = features.get("rates")
    if not isinstance(rates, dict) or any(k not in rates for k in ("s", "d", "t", "hr")):
        raise TotalBasesEngineError("rates must contain s,d,t,hr")
    rr = np.array([_finite(f"rates.{k}", rates[k], 0, 1) for k in ("s", "d", "t", "hr")])
    if rr.sum() >= 1:
        raise TotalBasesEngineError("hit event rates must sum to < 1")
    p_h = _finite("p_h", features.get("p_h"), 1e-8, 1)
    p_hr = _finite("p_hr", features.get("p_hr"), 1e-8, 1)
    park = _finite("park", features.get("park"), 0.01, 10)
    pool = _pa_pool(features.get("pa_pool"))
    lineup_status = model_input.get("lineup_status")
    if lineup_status not in ("CONFIRMED", "PROJECTED"):
        raise TotalBasesEngineError("invalid lineup_status")
    req = model_input.get("require_confirmed_lineup", False)
    if type(req) is not bool:
        raise TotalBasesEngineError("require_confirmed_lineup must be boolean")
    if req and lineup_status != "CONFIRMED":
        raise TotalBasesEngineError("confirmed lineup required")
    return rr, p_h, p_hr, park, pool


def _scaled_rates(rates: np.ndarray, p_h: float, p_hr: float, park: float) -> np.ndarray:
    contact = (p_h / LG_P_H) ** BATTER_HIT_EXPONENT
    hr_adj = (p_hr / LG_P_HR) ** PITCHER_HR_EXPONENT
    park_adj = park ** PARK_EXPONENT
    out = rates.copy()
    out[:3] *= contact
    out[3] *= hr_adj * park_adj
    return np.clip(out * TRAIN_SCALE, 1e-5, 0.5)


def simulate_total_bases(model_input: dict, thresholds=(0.5, 1.5, 2.5), n_sim: int = N_MC_PATHS) -> TotalBasesModelOutput:
    rates, p_h, p_hr, park, own_pool = _validate(model_input)
    if isinstance(n_sim, bool) or not isinstance(n_sim, int) or n_sim <= 0:
        raise TotalBasesEngineError("n_sim must be a positive integer")
    clean = []
    for x in thresholds:
        t = _finite("threshold", x, 0)
        clean.append(t)

    rng = candidate_numpy_rng(model_input["build_hash"])
    weight = len(own_pool) / (len(own_pool) + WORKLOAD_SHRINK)
    own = rng.random(n_sim) < weight
    pa = np.empty(n_sim, dtype=np.int64)
    n_own = int(own.sum())
    if n_own:
        pa[own] = rng.choice(own_pool, size=n_own, replace=True)
    if n_sim - n_own:
        pa[~own] = rng.choice(TRAIN_PA_POOL, size=n_sim - n_own, replace=True)

    ps = _scaled_rates(rates, p_h, p_hr, park)
    game_factor = sample_game_effect(n_sim, rng, SIGMA_GAME_EFFECT)
    cumulative = np.cumsum(ps[None, :] * game_factor[:, None], axis=1)
    u = rng.random((n_sim, MAX_PA_SLOTS))
    values = np.zeros((n_sim, MAX_PA_SLOTS), dtype=np.int8)
    values[u < cumulative[:, 3:4]] = 4
    values[u < cumulative[:, 2:3]] = 3
    values[u < cumulative[:, 1:2]] = 2
    values[u < cumulative[:, 0:1]] = 1
    mask = np.arange(MAX_PA_SLOTS)[None, :] < pa[:, None]
    total_bases = (values * mask).sum(axis=1)
    probs = {t: float((total_bases > t).mean()) for t in clean}
    return TotalBasesModelOutput(
        ENGINE_VERSION, model_input["build_hash"], "identity_sha256_seedsequence_256bit",
        SIGMA_GAME_EFFECT, n_sim, model_input["lineup_status"], probs,
    )
