"""Simple, transparent distribution pricing for MLB prop markets.

These functions turn structural projections into market probabilities. They are
not promotion evidence and do not bypass downstream market/Truth Gate checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial, isfinite

from sportsedge.mlb.environment_effects import EnvironmentEffects


@dataclass(frozen=True)
class PropProbability:
    market: str
    line: float
    over_prob: float
    under_prob: float
    push_prob: float = 0.0
    promotion_evidence: bool = False

    def __post_init__(self) -> None:
        total = self.over_prob + self.under_prob + self.push_prob
        if not all(isfinite(v) and v >= 0 for v in (self.over_prob, self.under_prob, self.push_prob)):
            raise ValueError("probabilities must be finite and non-negative")
        if abs(total - 1.0) > 1e-9:
            raise ValueError("probabilities must sum to one")


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0 or not isfinite(lam):
        raise ValueError("Poisson mean must be finite and > 0")
    return exp(-lam) * (lam ** k) / factorial(k)


def poisson_line(mean: float, line: float, *, market: str) -> PropProbability:
    """Price integer-count props from a Poisson approximation.

    Handles half-lines and integer lines with push probability.
    """
    if mean <= 0 or not isfinite(mean):
        raise ValueError("mean must be finite and > 0")
    max_k = max(40, int(mean + 12 * (mean ** 0.5) + 10))
    probs = [_poisson_pmf(k, mean) for k in range(max_k + 1)]
    tail = max(0.0, 1.0 - sum(probs))
    over = under = push = 0.0
    integer_line = float(line).is_integer()
    for k, p in enumerate(probs):
        if k > line:
            over += p
        elif k < line:
            under += p
        else:
            push += p
    over += tail
    if not integer_line:
        push = 0.0
    total = over + under + push
    return PropProbability(market, line, over / total, under / total, push / total)


def hitter_hit_probability(*, per_pa_hit_prob: float, projected_pa: float) -> float:
    """Probability of at least one hit using effective plate appearances.

    This is a transparent Bernoulli approximation. projected_pa may be fractional.
    """
    if not 0 < per_pa_hit_prob < 1:
        raise ValueError("per_pa_hit_prob must be in (0,1)")
    if projected_pa <= 0:
        raise ValueError("projected_pa must be > 0")
    return 1.0 - (1.0 - per_pa_hit_prob) ** projected_pa


def total_bases_mean(*, per_pa_tb: float, projected_pa: float, env: EnvironmentEffects) -> float:
    if per_pa_tb <= 0 or projected_pa <= 0:
        raise ValueError("per_pa_tb and projected_pa must be > 0")
    # XBH conditions have more direct effect on TB than generic run environment.
    return per_pa_tb * projected_pa * (0.70 * env.xbh + 0.30 * env.hr)


def strikeout_mean(*, k_rate: float, projected_batters_faced: float, env: EnvironmentEffects) -> float:
    if not 0 < k_rate < 1:
        raise ValueError("k_rate must be in (0,1)")
    if projected_batters_faced <= 0:
        raise ValueError("projected_batters_faced must be > 0")
    return k_rate * projected_batters_faced * env.strikeouts


def hits_allowed_mean(*, xba_allowed: float, projected_batters_faced: float, env: EnvironmentEffects) -> float:
    if not 0 < xba_allowed < 1:
        raise ValueError("xba_allowed must be in (0,1)")
    if projected_batters_faced <= 0:
        raise ValueError("projected_batters_faced must be > 0")
    contact_env = 0.55 * env.runs + 0.30 * env.xbh + 0.15 * env.hr
    return xba_allowed * projected_batters_faced * contact_env


def recorded_outs_mean(*, projected_batters_faced: float, non_out_rate: float) -> float:
    if projected_batters_faced <= 0:
        raise ValueError("projected_batters_faced must be > 0")
    if not 0 < non_out_rate < 1:
        raise ValueError("non_out_rate must be in (0,1)")
    return projected_batters_faced * (1.0 - non_out_rate)
