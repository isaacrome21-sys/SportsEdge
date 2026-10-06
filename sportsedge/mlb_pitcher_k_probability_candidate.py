"""Research-only MLB pitcher-K probability candidate.

Implements the preregistered K/BF ridge-logit rate model and beta-binomial count
layer. This module deliberately emits candidate probabilities, not production
model_p, and grants no release authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import exp, floor, isfinite, lgamma, log
from typing import Any, Mapping, Sequence

import numpy as np

from .mlb_pitcher_k_probability_prereg import (
    CANDIDATE_FAMILY,
    CONCENTRATION_GRID,
    FEATURES,
    RIDGE_GRID,
)

INPUT_SCHEMA = "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"
OUTPUT_SCHEMA = "MLB_PITCHER_K_PROBABILITY_CANDIDATE_V1"
AUTHORITY = "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED"
HALF_LINES = tuple(x + 0.5 for x in range(20))


class PitcherKProbabilityCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class PitcherKRateFit:
    candidate_family: str
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    ridge_alpha: float
    training_rows: int
    training_batters_faced: int
    fit_sha256: str


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PitcherKProbabilityCandidateError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityCandidateError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise PitcherKProbabilityCandidateError(f"{name} must be finite")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0:
        raise PitcherKProbabilityCandidateError(f"{name} must be positive")
    return out


def _candidate_components(candidate: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(candidate, Mapping) or candidate.get("schema") != INPUT_SCHEMA:
        raise PitcherKProbabilityCandidateError("unexpected skill-bound candidate")
    if candidate.get("authority") != AUTHORITY:
        raise PitcherKProbabilityCandidateError("candidate must remain research only")
    if candidate.get("source_complete") is not True or candidate.get("missing_components"):
        raise PitcherKProbabilityCandidateError("candidate sources are incomplete")
    if candidate.get("deployment") is not False or candidate.get("model_p_eligible") is not False:
        raise PitcherKProbabilityCandidateError("candidate cannot already be deployable")
    components = candidate.get("components")
    if not isinstance(components, Mapping):
        raise PitcherKProbabilityCandidateError("candidate components required")
    workload = components.get("workload_leash")
    opponent = components.get("opponent_k")
    lineup = components.get("lineup_k")
    skill = components.get("pitcher_skill")
    if not isinstance(workload, Mapping) or not isinstance(workload.get("summary"), Mapping):
        raise PitcherKProbabilityCandidateError("workload summary required")
    if not isinstance(opponent, Mapping):
        raise PitcherKProbabilityCandidateError("opponent-K component required")
    if lineup is not None and not isinstance(lineup, Mapping):
        raise PitcherKProbabilityCandidateError("lineup-K component invalid")
    if not isinstance(skill, Mapping):
        raise PitcherKProbabilityCandidateError("pitcher skill component required")
    return workload["summary"], opponent, lineup, skill


def feature_vector(candidate: Mapping[str, Any]) -> tuple[float, ...]:
    workload, opponent, lineup, skill = _candidate_components(candidate)
    hand = str(skill.get("pitcher_hand") or "").upper()
    if hand not in {"L", "R"}:
        raise PitcherKProbabilityCandidateError("pitcher hand must be L or R")
    lineup_target = 1.0 if lineup is None else _positive(
        lineup.get("target_deviation"), "lineup.target_deviation"
    )
    values = (
        _positive(workload.get("recent_mean_batters_faced"), "recent_mean_batters_faced"),
        _positive(workload.get("recent_mean_k_per_batter_faced"), "recent_mean_k_per_batter_faced"),
        _positive(workload.get("recent_mean_pitches_per_batter_faced"), "recent_mean_pitches_per_batter_faced"),
        _positive(opponent.get("target_rel"), "opponent.target_rel"),
        lineup_target,
        _positive(skill.get("whiff_rate"), "skill.whiff_rate"),
        _positive(skill.get("chase_rate"), "skill.chase_rate"),
        1.0 if hand == "R" else 0.0,
    )
    if values[1] >= 1 or values[5] >= 1 or values[6] >= 1:
        raise PitcherKProbabilityCandidateError("rate features must be in (0,1)")
    return tuple(float(v) for v in values)


def projected_batters_faced(candidate: Mapping[str, Any]) -> int:
    bf = int(round(feature_vector(candidate)[0]))
    if not 1 <= bf <= 50:
        raise PitcherKProbabilityCandidateError("projected batters faced outside [1,50]")
    return bf


def _row(row: Mapping[str, Any]) -> tuple[tuple[float, ...], int, int]:
    if not isinstance(row, Mapping):
        raise PitcherKProbabilityCandidateError("training row must be object")
    candidate = row.get("candidate")
    if not isinstance(candidate, Mapping):
        raise PitcherKProbabilityCandidateError("training row candidate required")
    try:
        k = int(row.get("realized_strikeouts"))
        bf = int(row.get("realized_batters_faced"))
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityCandidateError("realized K/BF must be integers") from exc
    if bf <= 0 or k < 0 or k > bf:
        raise PitcherKProbabilityCandidateError("realized K/BF impossible")
    return feature_vector(candidate), k, bf


def _digest(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def fit_rate_model(rows: Sequence[Mapping[str, Any]], *, ridge_alpha: float) -> PitcherKRateFit:
    alpha = _positive(ridge_alpha, "ridge_alpha")
    if not any(abs(alpha - x) <= 1e-12 for x in RIDGE_GRID):
        raise PitcherKProbabilityCandidateError("ridge alpha outside preregistered grid")
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
        raise PitcherKProbabilityCandidateError("training rows required")

    parsed = [_row(row) for row in rows]
    raw_x = np.asarray([item[0] for item in parsed], dtype=float)
    successes = np.asarray([item[1] for item in parsed], dtype=float)
    trials = np.asarray([item[2] for item in parsed], dtype=float)
    means = raw_x.mean(axis=0)
    scales = raw_x.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    z_x = (raw_x - means) / scales
    design = np.column_stack([np.ones(len(parsed)), z_x])

    overall = float(successes.sum() / trials.sum())
    overall = min(1 - 1e-6, max(1e-6, overall))
    beta = np.zeros(design.shape[1], dtype=float)
    beta[0] = log(overall / (1.0 - overall))
    penalty = np.diag([0.0] + [alpha] * (design.shape[1] - 1))

    for _ in range(100):
        eta = np.clip(design @ beta, -30.0, 30.0)
        p = 1.0 / (1.0 + np.exp(-eta))
        variance = np.maximum(p * (1.0 - p), 1e-8)
        weights = trials * variance
        response = successes / trials
        working = eta + (response - p) / variance
        lhs = design.T @ (weights[:, None] * design) + penalty
        rhs = design.T @ (weights * working)
        try:
            updated = np.linalg.solve(lhs, rhs)
        except np.linalg.LinAlgError:
            updated = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
        if float(np.max(np.abs(updated - beta))) < 1e-10:
            beta = updated
            break
        beta = updated

    payload = {
        "candidate_family": CANDIDATE_FAMILY,
        "feature_names": list(FEATURES),
        "means": means.tolist(),
        "scales": scales.tolist(),
        "coefficients": beta.tolist(),
        "ridge_alpha": alpha,
        "training_rows": len(parsed),
        "training_batters_faced": int(trials.sum()),
    }
    return PitcherKRateFit(
        candidate_family=CANDIDATE_FAMILY,
        feature_names=tuple(FEATURES),
        means=tuple(float(v) for v in means),
        scales=tuple(float(v) for v in scales),
        coefficients=tuple(float(v) for v in beta),
        ridge_alpha=alpha,
        training_rows=len(parsed),
        training_batters_faced=int(trials.sum()),
        fit_sha256=_digest(payload),
    )


def predict_k_rate(fit: PitcherKRateFit, candidate: Mapping[str, Any]) -> float:
    if fit.candidate_family != CANDIDATE_FAMILY or tuple(fit.feature_names) != tuple(FEATURES):
        raise PitcherKProbabilityCandidateError("fit identity mismatch")
    x = np.asarray(feature_vector(candidate), dtype=float)
    means = np.asarray(fit.means, dtype=float)
    scales = np.asarray(fit.scales, dtype=float)
    beta = np.asarray(fit.coefficients, dtype=float)
    if len(beta) != len(FEATURES) + 1:
        raise PitcherKProbabilityCandidateError("fit coefficient shape mismatch")
    eta = float(beta[0] + ((x - means) / scales) @ beta[1:])
    eta = min(30.0, max(-30.0, eta))
    return float(1.0 / (1.0 + exp(-eta)))


def _binomial_logpmf(k: int, n: int, p: float) -> float:
    return (
        lgamma(n + 1.0) - lgamma(k + 1.0) - lgamma(n - k + 1.0)
        + k * log(p) + (n - k) * log(1.0 - p)
    )


def _beta_binomial_logpmf(k: int, n: int, p: float, concentration: float) -> float:
    a = p * concentration
    b = (1.0 - p) * concentration
    return (
        lgamma(n + 1.0) - lgamma(k + 1.0) - lgamma(n - k + 1.0)
        + lgamma(k + a) + lgamma(n - k + b) - lgamma(n + a + b)
        + lgamma(a + b) - lgamma(a) - lgamma(b)
    )


def count_mass(*, n_trials: int, k_rate: float, concentration: float) -> tuple[float, ...]:
    n = int(n_trials)
    if not 1 <= n <= 50:
        raise PitcherKProbabilityCandidateError("n_trials outside [1,50]")
    p = _finite(k_rate, "k_rate")
    if not 0 < p < 1:
        raise PitcherKProbabilityCandidateError("k_rate must be inside (0,1)")
    c = _positive(concentration, "concentration")
    if not any(abs(c - x) <= 1e-9 * max(1.0, x) for x in CONCENTRATION_GRID):
        raise PitcherKProbabilityCandidateError("concentration outside preregistered grid")

    logs = []
    for k in range(n + 1):
        logs.append(
            _binomial_logpmf(k, n, p)
            if c >= 1e8
            else _beta_binomial_logpmf(k, n, p, c)
        )
    peak = max(logs)
    raw = [exp(v - peak) for v in logs]
    total = sum(raw)
    return tuple(v / total for v in raw)


def price_threshold(
    candidate: Mapping[str, Any],
    fit: PitcherKRateFit,
    *,
    concentration: float,
    line: float,
) -> dict[str, Any]:
    threshold = _finite(line, "line")
    if threshold < 0:
        raise PitcherKProbabilityCandidateError("line must be nonnegative")
    n = projected_batters_faced(candidate)
    rate = predict_k_rate(fit, candidate)
    mass = count_mass(n_trials=n, k_rate=rate, concentration=concentration)
    p_over = sum(p for k, p in enumerate(mass) if k > threshold)
    p_under = sum(p for k, p in enumerate(mass) if k < threshold)
    p_push = sum(p for k, p in enumerate(mass) if k == threshold)
    total = p_over + p_under + p_push
    if abs(total - 1.0) > 1e-9:
        raise PitcherKProbabilityCandidateError("probability mass does not conserve")
    payload = {
        "schema": OUTPUT_SCHEMA,
        "authority": AUTHORITY,
        "candidate_family": CANDIDATE_FAMILY,
        "fit_sha256": fit.fit_sha256,
        "ridge_alpha": fit.ridge_alpha,
        "concentration": float(concentration),
        "projected_batters_faced": n,
        "predicted_k_per_batter_faced": rate,
        "line": threshold,
        "candidate_p_over": float(p_over),
        "candidate_p_under": float(p_under),
        "candidate_p_push": float(p_push),
        "deployment": False,
        "model_p_eligible": False,
    }
    payload["readout_sha256"] = _digest(payload)
    return payload


def rps_for_realized_count(
    candidate: Mapping[str, Any],
    fit: PitcherKRateFit,
    *,
    concentration: float,
    realized_strikeouts: int,
) -> float:
    y = int(realized_strikeouts)
    if y < 0:
        raise PitcherKProbabilityCandidateError("realized strikeouts must be nonnegative")
    errors = []
    for line in HALF_LINES:
        p = price_threshold(candidate, fit, concentration=concentration, line=line)["candidate_p_over"]
        errors.append((float(p) - (1.0 if y > line else 0.0)) ** 2)
    return float(sum(errors) / len(errors))


def select_hyperparameters(
    training_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not validation_rows:
        raise PitcherKProbabilityCandidateError("validation rows required")
    scored = []
    for alpha in RIDGE_GRID:
        fit = fit_rate_model(training_rows, ridge_alpha=alpha)
        for concentration in CONCENTRATION_GRID:
            values = []
            for row in validation_rows:
                _, realized_k, _ = _row(row)
                values.append(
                    rps_for_realized_count(
                        row["candidate"],
                        fit,
                        concentration=concentration,
                        realized_strikeouts=realized_k,
                    )
                )
            scored.append(
                {
                    "ridge_alpha": float(alpha),
                    "concentration": float(concentration),
                    "mean_rps": float(sum(values) / len(values)),
                    "fit_sha256": fit.fit_sha256,
                }
            )
    scored.sort(key=lambda r: (r["mean_rps"], -r["ridge_alpha"], -r["concentration"]))
    best = dict(scored[0])
    best["grid_scores"] = scored
    return best


def fit_payload(fit: PitcherKRateFit) -> dict[str, Any]:
    return asdict(fit)
