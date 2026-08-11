"""Shared game-level effect sampler used by validated hitter Hits/TB models.

sigma=0.20 was fit on 2021-2022 training data only and frozen before scoring
2023-2024. Hits improved 7.56 SE -> 2.63 SE and Total Bases 5.32 SE ->
1.60 SE using the same sigma without TB refitting.
"""
import numpy as np

SIGMA_GAME_EFFECT = 0.20
CODE_VERSION = "shared_game_effect_v1.0"


def sample_game_effect(n_sim: int, rng: np.random.Generator,
                       sigma: float = SIGMA_GAME_EFFECT) -> np.ndarray:
    """Return one mean-one lognormal multiplicative factor per game path."""
    if isinstance(n_sim, bool) or not isinstance(n_sim, int) or n_sim <= 0:
        raise ValueError("n_sim must be a positive integer")
    if not np.isfinite(sigma) or sigma < 0:
        raise ValueError("sigma must be finite and non-negative")
    return rng.lognormal(-0.5 * sigma**2, sigma, n_sim)


def apply_shared_game_effect(base_rates: np.ndarray, n_sim: int,
                             rng: np.random.Generator,
                             sigma: float = SIGMA_GAME_EFFECT,
                             clip_lo: float = 1e-5,
                             clip_hi: float = 0.9) -> np.ndarray:
    """Scale all batter rates on one MC path by the same game-level draw."""
    base = np.atleast_1d(np.asarray(base_rates, dtype=float))
    if base.ndim != 1 or base.size == 0 or not np.all(np.isfinite(base)):
        raise ValueError("base_rates must be a non-empty finite 1-D array")
    if not np.isfinite(clip_lo) or not np.isfinite(clip_hi) or not 0 <= clip_lo < clip_hi <= 1:
        raise ValueError("invalid probability clipping bounds")
    gfac = sample_game_effect(n_sim, rng, sigma)
    scaled = base[None, :] * gfac[:, None]
    return np.clip(scaled, clip_lo, clip_hi).squeeze()
