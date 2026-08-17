"""Football joint-score simulator with explicit NFL key-number mass."""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from typing import Iterable

import numpy as np


def _normal_cdf(x: float, mean: float, sigma: float) -> float:
    z = (x - mean) / (sigma * sqrt(2.0))
    return 0.5 * (1.0 + erf(z))


@dataclass(frozen=True)
class KeyNumberMarginModel:
    """Discrete margin PMF with empirical point masses at key numbers.

    ``empirical_key_mass`` is absolute probability mass, not a multiplier. The
    remaining probability is allocated across non-key integer margins using a
    discretized normal. This prevents the common smooth-normal mispricing near
    3 and 7 while keeping the model diagnosable.
    """

    mean: float
    sigma: float
    empirical_key_mass: dict[int, float]

    def __post_init__(self) -> None:
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")
        if any(value < 0 for value in self.empirical_key_mass.values()):
            raise ValueError("key-number masses must be nonnegative")
        if sum(self.empirical_key_mass.values()) >= 1.0:
            raise ValueError("key-number masses must sum to less than 1")

    def margin_pmf(self, support: Iterable[int]) -> dict[int, float]:
        values = sorted({int(x) for x in support})
        if not values:
            raise ValueError("support must be nonempty")
        missing_keys = set(self.empirical_key_mass) - set(values)
        if missing_keys:
            raise ValueError(f"support missing key margins: {sorted(missing_keys)}")

        base: dict[int, float] = {}
        for margin in values:
            if margin in self.empirical_key_mass:
                continue
            lo = margin - 0.5
            hi = margin + 0.5
            base[margin] = max(0.0, _normal_cdf(hi, self.mean, self.sigma) - _normal_cdf(lo, self.mean, self.sigma))

        remaining = 1.0 - sum(self.empirical_key_mass.values())
        base_total = sum(base.values())
        if base_total <= 0:
            raise ValueError("normal component has no probability mass on support")

        pmf = {margin: probability * remaining / base_total for margin, probability in base.items()}
        pmf.update({int(k): float(v) for k, v in self.empirical_key_mass.items()})
        # Numerical cleanup without moving empirical key masses.
        residual = 1.0 - sum(pmf.values())
        if abs(residual) > 1e-15:
            first_nonkey = next(m for m in values if m not in self.empirical_key_mass)
            pmf[first_nonkey] += residual
        return dict(sorted(pmf.items()))


class JointScoreSimulator:
    """Simulate internally consistent home/away integer football scores."""

    def __init__(
        self,
        margin_model: KeyNumberMarginModel,
        total_mean: float,
        total_sigma: float,
        seed: int | None = None,
    ) -> None:
        if total_sigma <= 0:
            raise ValueError("total_sigma must be positive")
        self.margin_model = margin_model
        self.total_mean = float(total_mean)
        self.total_sigma = float(total_sigma)
        self.rng = np.random.default_rng(seed)

    def simulate(self, n: int) -> list[dict[str, int]]:
        if n <= 0:
            return []
        support = np.arange(-80, 81, dtype=int)
        pmf = self.margin_model.margin_pmf(support.tolist())
        margins = self.rng.choice(np.array(list(pmf), dtype=int), size=n, p=np.array(list(pmf.values()), dtype=float))
        raw_totals = np.rint(self.rng.normal(self.total_mean, self.total_sigma, size=n)).astype(int)

        rows: list[dict[str, int]] = []
        for margin, raw_total in zip(margins.tolist(), raw_totals.tolist()):
            total = max(abs(int(margin)), max(0, int(raw_total)))
            if (total - int(margin)) % 2 != 0:
                total += 1
            home = (total + int(margin)) // 2
            away = (total - int(margin)) // 2
            rows.append(
                {
                    "home_score": int(home),
                    "away_score": int(away),
                    "margin": int(home - away),
                    "total": int(home + away),
                }
            )
        return rows
