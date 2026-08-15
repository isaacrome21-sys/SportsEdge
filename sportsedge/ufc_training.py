"""Chronological UFC model fitting utilities.

This module keeps training time-safe: rows must contain only features known before
fight time. It implements a small dependency-free logistic learner, Elo updates,
Platt calibration, and walk-forward evaluation so CI can validate calibration
without importing sklearn.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from statistics import mean
from typing import Iterable, Mapping, Sequence


FEATURES = (
    "elo_diff", "age_diff", "reach_diff", "height_diff", "slpm_diff", "sapm_diff",
    "str_acc_diff", "str_def_diff", "td_avg_diff", "td_acc_diff", "td_def_diff",
    "sub_avg_diff", "recent_win_rate_diff", "sos_diff", "rest_days_diff",
    "late_replacement_diff", "experience_diff",
)


@dataclass(frozen=True)
class TrainingRow:
    fight_date: str
    event: str
    fighter_a: str
    fighter_b: str
    y_a_win: int
    features: Mapping[str, float]


@dataclass(frozen=True)
class LogisticArtifact:
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    means: tuple[float, ...]
    scales: tuple[float, ...]
    platt_a: float = 1.0
    platt_b: float = 0.0

    def raw_probability(self, features: Mapping[str, float]) -> float:
        z = self.intercept
        for name, coef, mu, scale in zip(self.feature_names, self.coefficients, self.means, self.scales):
            x = (float(features.get(name, 0.0)) - mu) / scale
            z += coef * x
        return _sigmoid(z)

    def probability(self, features: Mapping[str, float]) -> float:
        p = min(1 - 1e-9, max(1e-9, self.raw_probability(features)))
        score = log(p / (1 - p))
        return _sigmoid(self.platt_a * score + self.platt_b)

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_names": list(self.feature_names),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "means": list(self.means),
            "scales": list(self.scales),
            "platt_a": self.platt_a,
            "platt_b": self.platt_b,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "LogisticArtifact":
        return cls(
            feature_names=tuple(str(x) for x in value["feature_names"]),
            coefficients=tuple(float(x) for x in value["coefficients"]),
            intercept=float(value["intercept"]),
            means=tuple(float(x) for x in value["means"]),
            scales=tuple(float(x) for x in value["scales"]),
            platt_a=float(value.get("platt_a", 1.0)),
            platt_b=float(value.get("platt_b", 0.0)),
        )


@dataclass(frozen=True)
class EvalMetrics:
    n: int
    log_loss: float
    brier: float
    accuracy: float
    calibration_error: float


def _sigmoid(z: float) -> float:
    if z >= 0:
        e = exp(-z)
        return 1.0 / (1.0 + e)
    e = exp(z)
    return e / (1.0 + e)


def _standardize(rows: Sequence[TrainingRow], names: Sequence[str]) -> tuple[list[list[float]], list[float], list[float]]:
    cols = [[float(r.features.get(name, 0.0)) for r in rows] for name in names]
    mus = [mean(c) if c else 0.0 for c in cols]
    scales = []
    for c, mu in zip(cols, mus):
        var = mean([(x - mu) ** 2 for x in c]) if c else 0.0
        scales.append(max(var ** 0.5, 1e-6))
    X = [[(float(r.features.get(name, 0.0)) - mu) / s for name, mu, s in zip(names, mus, scales)] for r in rows]
    return X, mus, scales


def fit_logistic(rows: Sequence[TrainingRow], *, feature_names: Sequence[str] = FEATURES,
                 epochs: int = 2500, lr: float = 0.03, l2: float = 0.002) -> LogisticArtifact:
    if len(rows) < 20:
        raise ValueError("UFC_TRAINING_ROWS_INSUFFICIENT")
    X, mus, scales = _standardize(rows, feature_names)
    y = [int(r.y_a_win) for r in rows]
    w = [0.0] * len(feature_names)
    b = 0.0
    n = float(len(rows))
    for _ in range(epochs):
        gw = [0.0] * len(w)
        gb = 0.0
        for xi, yi in zip(X, y):
            p = _sigmoid(b + sum(a * z for a, z in zip(w, xi)))
            err = p - yi
            gb += err
            for j, xij in enumerate(xi):
                gw[j] += err * xij
        b -= lr * gb / n
        for j in range(len(w)):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
    return LogisticArtifact(tuple(feature_names), tuple(w), b, tuple(mus), tuple(scales))


def fit_platt(artifact: LogisticArtifact, rows: Sequence[TrainingRow], *, epochs: int = 1500, lr: float = 0.02) -> LogisticArtifact:
    if not rows:
        return artifact
    scores = []
    ys = []
    for r in rows:
        p = min(1 - 1e-8, max(1e-8, artifact.raw_probability(r.features)))
        scores.append(log(p / (1 - p)))
        ys.append(int(r.y_a_win))
    a, b = 1.0, 0.0
    n = float(len(rows))
    for _ in range(epochs):
        ga = gb = 0.0
        for s, y in zip(scores, ys):
            p = _sigmoid(a * s + b)
            e = p - y
            ga += e * s
            gb += e
        a -= lr * ga / n
        b -= lr * gb / n
    return LogisticArtifact(artifact.feature_names, artifact.coefficients, artifact.intercept,
                            artifact.means, artifact.scales, a, b)


def evaluate(artifact: LogisticArtifact, rows: Sequence[TrainingRow], bins: int = 10) -> EvalMetrics:
    if not rows:
        return EvalMetrics(0, 0.0, 0.0, 0.0, 0.0)
    probs = [artifact.probability(r.features) for r in rows]
    ys = [int(r.y_a_win) for r in rows]
    ll = -mean([y * log(max(p, 1e-12)) + (1-y) * log(max(1-p, 1e-12)) for p, y in zip(probs, ys)])
    brier = mean([(p-y) ** 2 for p, y in zip(probs, ys)])
    acc = mean([1.0 if (p >= 0.5) == bool(y) else 0.0 for p, y in zip(probs, ys)])
    ce = 0.0
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        idx = [i for i, p in enumerate(probs) if lo <= p < hi or (k == bins - 1 and p == 1.0)]
        if idx:
            ce += (len(idx)/len(rows)) * abs(mean([probs[i] for i in idx]) - mean([ys[i] for i in idx]))
    return EvalMetrics(len(rows), ll, brier, acc, ce)


def chronological_split(rows: Sequence[TrainingRow], *, train_frac: float = 0.70, calibration_frac: float = 0.15):
    ordered = sorted(rows, key=lambda r: (r.fight_date, r.event, r.fighter_a, r.fighter_b))
    n = len(ordered)
    t = max(1, int(n * train_frac))
    c = max(t + 1, int(n * (train_frac + calibration_frac)))
    return ordered[:t], ordered[t:c], ordered[c:]


def fit_chronological(rows: Sequence[TrainingRow]) -> tuple[LogisticArtifact, EvalMetrics]:
    train, calibration, holdout = chronological_split(rows)
    model = fit_logistic(train)
    model = fit_platt(model, calibration)
    return model, evaluate(model, holdout)


def update_elo(rating_a: float, rating_b: float, result_a: float, *, k: float = 32.0) -> tuple[float, float]:
    expected_a = 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))
    delta = k * (result_a - expected_a)
    return rating_a + delta, rating_b - delta
