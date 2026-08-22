"""Deterministic Monte Carlo harness for MLB prop and first-inning pricing.

The default 10,000 draws mirror the public workflow we researched, but this is
SportsEdge's own transparent implementation. Simulation output remains research
pricing evidence only and cannot promote V6.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp
from random import Random


@dataclass(frozen=True)
class SimResult:
    market: str
    line: float
    simulations: int
    over_prob: float
    under_prob: float
    push_prob: float
    seed: int
    promotion_evidence: bool = False


def _poisson(rng: Random, lam: float) -> int:
    if lam <= 0:
        raise ValueError("lambda must be > 0")
    # Knuth is fast and exact for the small means typical of MLB count props.
    limit = exp(-lam)
    k = 0
    p = 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _uncertain_mean(rng: Random, mean: float, cv: float) -> float:
    if mean <= 0:
        raise ValueError("mean must be > 0")
    if cv < 0 or cv > 1:
        raise ValueError("mean_cv must be in [0,1]")
    if cv == 0:
        return mean
    # Bounded normal multiplier: uncertainty changes the event mean, not the
    # observed count itself. Floor prevents impossible negative intensities.
    return mean * max(0.15, rng.gauss(1.0, cv))


def simulate_count_line(
    *,
    mean: float,
    line: float,
    market: str,
    simulations: int = 10_000,
    mean_cv: float = 0.12,
    seed: int = 20260821,
) -> SimResult:
    if simulations < 1_000:
        raise ValueError("at least 1000 simulations required")
    rng = Random(seed)
    over = under = push = 0
    for _ in range(simulations):
        draw = _poisson(rng, _uncertain_mean(rng, mean, mean_cv))
        if draw > line:
            over += 1
        elif draw < line:
            under += 1
        else:
            push += 1
    return SimResult(market, line, simulations, over / simulations, under / simulations, push / simulations, seed)


def simulate_hitter_one_plus_hit(
    *,
    per_pa_hit_prob: float,
    projected_pa: float,
    simulations: int = 10_000,
    pa_sd: float = 0.45,
    seed: int = 20260821,
) -> float:
    if not 0 < per_pa_hit_prob < 1:
        raise ValueError("per_pa_hit_prob must be in (0,1)")
    if projected_pa <= 0 or pa_sd < 0:
        raise ValueError("invalid PA projection")
    rng = Random(seed)
    hits = 0
    for _ in range(simulations):
        pa = max(1, round(rng.gauss(projected_pa, pa_sd)))
        if any(rng.random() < per_pa_hit_prob for _ in range(pa)):
            hits += 1
    return hits / simulations


def simulate_nrfi(
    *,
    away_first_inning_run_mean: float,
    home_first_inning_run_mean: float,
    simulations: int = 10_000,
    mean_cv: float = 0.15,
    seed: int = 20260821,
) -> float:
    """Return P(NRFI) by simulating each half-inning run count separately."""
    if away_first_inning_run_mean <= 0 or home_first_inning_run_mean <= 0:
        raise ValueError("first-inning run means must be > 0")
    rng = Random(seed)
    no_runs = 0
    for _ in range(simulations):
        away_lam = _uncertain_mean(rng, away_first_inning_run_mean, mean_cv)
        home_lam = _uncertain_mean(rng, home_first_inning_run_mean, mean_cv)
        if _poisson(rng, away_lam) == 0 and _poisson(rng, home_lam) == 0:
            no_runs += 1
    return no_runs / simulations
