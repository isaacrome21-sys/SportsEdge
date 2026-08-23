"""Football joint-score simulator with emergent integer-margin probabilities.

Historical key-number frequencies are validation targets only. They are never
accepted as simulator inputs or reserved as exact probability mass.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from typing import Iterable, Mapping

import numpy as np


def _normal_cdf(x: float, mean: float, sigma: float) -> float:
    z = (x - mean) / (sigma * sqrt(2.0))
    return 0.5 * (1.0 + erf(z))


@dataclass(frozen=True)
class KeyNumberMarginModel:
    """Candidate integer-margin PMF with no imposed historical key mass.

    The class name is retained for API compatibility, but ``empirical_key_mass``
    is no longer a calibration input. Any non-empty value fails closed so the
    previous exact-mass contract cannot silently survive migration.

    This smooth candidate is not itself considered promoted NFL scoring dynamics;
    its ±3/±7 frequencies must emerge and pass held-out behavioral validation.
    """

    mean: float
    sigma: float
    empirical_key_mass: Mapping[int, float] | None = None

    def __post_init__(self) -> None:
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")
        if self.empirical_key_mass:
            raise ValueError("IMPOSED_KEY_MASS_PROHIBITED")

    def margin_pmf(self, support: Iterable[int]) -> dict[int, float]:
        values = sorted({int(x) for x in support})
        if not values:
            raise ValueError("support must be nonempty")
        base: dict[int, float] = {}
        for margin in values:
            lo = margin - 0.5
            hi = margin + 0.5
            base[margin] = max(
                0.0,
                _normal_cdf(hi, self.mean, self.sigma)
                - _normal_cdf(lo, self.mean, self.sigma),
            )
        total = sum(base.values())
        if total <= 0:
            raise ValueError("normal component has no probability mass on support")
        pmf = {margin: probability / total for margin, probability in base.items()}
        residual = 1.0 - sum(pmf.values())
        if abs(residual) > 1e-15:
            pmf[values[0]] += residual
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
        margins = self.rng.choice(
            np.array(list(pmf), dtype=int),
            size=n,
            p=np.array(list(pmf.values()), dtype=float),
        )
        raw_totals = np.rint(
            self.rng.normal(self.total_mean, self.total_sigma, size=n)
        ).astype(int)

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
