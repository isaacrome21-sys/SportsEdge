from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Iterable, Sequence


class MLBUncertaintyError(ValueError):
    pass


@dataclass(frozen=True)
class BetaPosterior:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def beta_posterior(*, successes: float, trials: float, prior_mean: float, prior_strength: float) -> BetaPosterior:
    """Research-only conjugate shrinkage for rates such as K%, BB%, HR/PA.

    prior_strength is effective prior trials. Inputs must be point-in-time.
    """
    if trials < 0 or successes < 0 or successes > trials:
        raise MLBUncertaintyError("invalid successes/trials")
    if not 0 < prior_mean < 1 or prior_strength <= 0:
        raise MLBUncertaintyError("invalid prior")
    a0 = prior_mean * prior_strength
    b0 = (1.0 - prior_mean) * prior_strength
    return BetaPosterior(a0 + successes, b0 + trials - successes)


def sample_beta(posterior: BetaPosterior, rng: random.Random) -> float:
    return rng.betavariate(posterior.alpha, posterior.beta)


def sample_truncated_normal(*, mean: float, sd: float, low: float, high: float,
                            rng: random.Random, attempts: int = 100) -> float:
    if not math.isfinite(mean) or not math.isfinite(sd) or sd < 0 or low > high:
        raise MLBUncertaintyError("invalid normal parameters")
    if sd == 0:
        return min(high, max(low, mean))
    for _ in range(attempts):
        x = rng.gauss(mean, sd)
        if low <= x <= high:
            return x
    return min(high, max(low, mean))


@dataclass(frozen=True)
class SimulationSummary:
    n: int
    mean: float
    sd: float
    q05: float
    q50: float
    q95: float
    probability_over: float | None


def summarize_draws(draws: Sequence[float], *, over_line: float | None = None) -> SimulationSummary:
    if not draws:
        raise MLBUncertaintyError("draws must be non-empty")
    xs = sorted(float(x) for x in draws)
    if any(not math.isfinite(x) for x in xs):
        raise MLBUncertaintyError("draws must be finite")
    n = len(xs)
    mean = sum(xs) / n
    variance = sum((x - mean) ** 2 for x in xs) / n
    def q(p: float) -> float:
        idx = min(n - 1, max(0, round((n - 1) * p)))
        return xs[idx]
    p_over = None if over_line is None else sum(x > over_line for x in xs) / n
    return SimulationSummary(n, mean, math.sqrt(variance), q(.05), q(.50), q(.95), p_over)


def expected_value_decimal(*, win_probability: float, decimal_odds: float) -> float:
    if not 0 <= win_probability <= 1 or decimal_odds <= 1:
        raise MLBUncertaintyError("invalid EV inputs")
    return win_probability * (decimal_odds - 1.0) - (1.0 - win_probability)


def uncertainty_haircut(*, raw_edge: float, probability_sd: float, z: float = 1.0) -> float:
    """Conservative research ranking edge; cannot create an edge."""
    if probability_sd < 0 or z < 0:
        raise MLBUncertaintyError("invalid uncertainty inputs")
    if raw_edge <= 0:
        return raw_edge
    return max(0.0, raw_edge - z * probability_sd)
