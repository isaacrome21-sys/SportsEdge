#!/usr/bin/env python3
"""Shared game-level effect sampler packaged from independently validated research.

Promotion status: MODULE PRESENT / DEPLOYMENT CAPABILITY NOT YET ATTESTED.
The runtime capability flag must remain false until the acceptance fixture and
full production path reproduce the validated Hits/TB calibration.
"""
import numpy as np

SIGMA_GAME_EFFECT = 0.20
CODE_VERSION = "shared_game_effect_v1.0"


def sample_game_effect(n_sim: int, rng: np.random.Generator,
                       sigma: float = SIGMA_GAME_EFFECT) -> np.ndarray:
    return rng.lognormal(-0.5 * sigma**2, sigma, n_sim)


def apply_shared_game_effect(base_rates: np.ndarray, n_sim: int,
                             rng: np.random.Generator,
                             sigma: float = SIGMA_GAME_EFFECT,
                             clip_lo: float = 1e-5, clip_hi: float = 0.9) -> np.ndarray:
    gfac = sample_game_effect(n_sim, rng, sigma)
    base = np.atleast_1d(base_rates)
    scaled = base[None, :] * gfac[:, None]
    return np.clip(scaled, clip_lo, clip_hi).squeeze()


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    rates = np.array([0.28, 0.31])
    out = apply_shared_game_effect(rates, 5, rng)
    assert out.shape == (5, 2)
    assert SIGMA_GAME_EFFECT == 0.20
    print("shared game effect smoke test OK")
