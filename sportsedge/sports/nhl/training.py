"""PIT-safe NHL rate fitting and probability calibration.

No production coefficients live here. Callers supply temporally eligible training
rows; fitted artifacts retain deterministic provenance and must be evaluated on
future holdouts.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable

from .rate_model import NHLRateParameters

FEATURES = ("offense_xg", "opponent_xga", "shot_share", "special_teams",
            "goalie_gsax", "rest", "travel", "lineup", "home_ice")


@dataclass(frozen=True)
class NHLRateTrainingRow:
    game_id: str
    settled_at: str
    features: tuple[float, ...]
    goals: int

    def validate(self) -> None:
        if not self.game_id or len(self.features) != len(FEATURES):
            raise ValueError("complete training identity/features required")
        if self.goals < 0 or any(not math.isfinite(x) for x in self.features):
            raise ValueError("finite features and nonnegative goals required")


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [a[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("singular training design")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [v / scale for v in aug[col]]
        for r in range(n):
            if r == col:
                continue
            f = aug[r][col]
            aug[r] = [x - f * y for x, y in zip(aug[r], aug[col])]
    return [aug[i][-1] for i in range(n)]


def fit_rate_parameters(rows: Iterable[NHLRateTrainingRow], *, version: str,
                        ridge: float = 1.0) -> NHLRateParameters:
    """Fit a transparent log-goal ridge baseline; no market prices are inputs."""
    data = list(rows)
    if not version or ridge < 0 or len(data) < len(FEATURES) + 2:
        raise ValueError("version and sufficient training rows required")
    for r in data:
        r.validate()
    x = [[1.0, *r.features] for r in data]
    y = [math.log(r.goals + 0.5) for r in data]
    p = len(x[0])
    gram = [[sum(row[i] * row[j] for row in x) for j in range(p)] for i in range(p)]
    rhs = [sum(row[i] * target for row, target in zip(x, y)) for i in range(p)]
    for i in range(1, p):
        gram[i][i] += ridge
    beta = _solve(gram, rhs)
    return NHLRateParameters(version, *beta)


@dataclass(frozen=True)
class NHLCalibrationArtifact:
    version: str
    method: str
    bins: tuple[tuple[float, float], ...]
    training_sha256: str

    def calibrate(self, probability: float) -> float:
        if not 0 <= probability <= 1:
            raise ValueError("probability must be in [0,1]")
        if not self.bins:
            return probability
        return min(self.bins, key=lambda pair: abs(pair[0] - probability))[1]


def fit_binned_calibrator(probabilities: Iterable[float], outcomes: Iterable[int], *,
                          version: str, bins: int = 10) -> NHLCalibrationArtifact:
    ps, ys = list(probabilities), list(outcomes)
    if not version or len(ps) != len(ys) or not ps or bins < 2:
        raise ValueError("aligned nonempty calibration sample required")
    if any(not 0 <= p <= 1 for p in ps) or any(y not in (0, 1) for y in ys):
        raise ValueError("invalid calibration observations")
    grouped: list[tuple[float, float]] = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, p in enumerate(ps) if lo <= p <= hi if i == bins - 1 or p < hi]
        if idx:
            grouped.append((sum(ps[j] for j in idx) / len(idx), sum(ys[j] for j in idx) / len(idx)))
    raw = json.dumps(list(zip(ps, ys)), separators=(",", ":"), allow_nan=False).encode()
    return NHLCalibrationArtifact(version, "binned_holdout_v1", tuple(grouped), hashlib.sha256(raw).hexdigest())
