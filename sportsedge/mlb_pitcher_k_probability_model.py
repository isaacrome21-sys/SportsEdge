"""Deterministic implementation of the frozen MLB pitcher-K probability candidate.

Contract: config/research/mlb_pitcher_k_probability_prereg_v1.json
Candidate: RIDGE_LOGIT_K_RATE_BETA_BINOMIAL_V1

This module is research-only.  It fits/selects the preregistered development
candidate and evaluates a caller-supplied untouched candidate-test set.  It does
not fetch outcomes, read sportsbook prices, create Model_P, or grant release
authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, floor, isfinite, lgamma, log
from typing import Any, Mapping, Sequence

import numpy as np

CANDIDATE_FAMILY = "RIDGE_LOGIT_K_RATE_BETA_BINOMIAL_V1"
ARTIFACT_SCHEMA = "MLB_PITCHER_K_PROBABILITY_FIT_V1"
FEATURE_NAMES = (
    "recent_mean_batters_faced",
    "recent_mean_k_per_batter_faced",
    "recent_mean_pitches_per_batter_faced",
    "opponent_target_rel",
    "lineup_target_deviation_or_1",
    "whiff_rate",
    "chase_rate",
    "pitcher_hand_R",
)
RIDGE_GRID = (0.1, 1.0, 10.0, 100.0)
CONCENTRATION_GRID = (20.0, 50.0, 100.0, 200.0, 1_000_000_000.0)
HALF_LINES = tuple(i + 0.5 for i in range(20))
TYPICAL_LINES = (3.5, 4.5, 5.5, 6.5)
BOOT_REPS = 2000
BOOT_SEED = 20261006
MIN_TEST_STARTS = 500
AUTHORITY = "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED"


class PitcherKProbabilityModelError(ValueError):
    pass


@dataclass(frozen=True)
class _Design:
    x: np.ndarray
    k: np.ndarray
    bf: np.ndarray
    pitcher_ids: tuple[int, ...]
    seasons: tuple[int, ...]


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PitcherKProbabilityModelError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityModelError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise PitcherKProbabilityModelError(f"{name} must be finite")
    return out


def _design(rows: Sequence[Mapping[str, Any]]) -> _Design:
    if not rows:
        raise PitcherKProbabilityModelError("rows required")
    xs: list[list[float]] = []
    ks: list[int] = []
    bfs: list[int] = []
    pitchers: list[int] = []
    seasons: list[int] = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise PitcherKProbabilityModelError(f"row {i} must be object")
        features = row.get("features")
        if not isinstance(features, Mapping):
            raise PitcherKProbabilityModelError(f"row {i}.features required")
        vector = [_number(features.get(name), f"row {i}.{name}") for name in FEATURE_NAMES]
        if vector[0] <= 0 or not 0 <= vector[1] <= 1 or vector[2] <= 0:
            raise PitcherKProbabilityModelError(f"row {i} workload features invalid")
        if vector[3] <= 0 or vector[4] <= 0:
            raise PitcherKProbabilityModelError(f"row {i} context indices invalid")
        if not 0 <= vector[5] <= 1 or not 0 <= vector[6] <= 1 or vector[7] not in {0.0, 1.0}:
            raise PitcherKProbabilityModelError(f"row {i} skill features invalid")
        try:
            k = int(row["y_k"])
            bf = int(row["y_bf"])
            pitcher = int(row["pitcher_id"])
            season = int(row["season"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PitcherKProbabilityModelError(f"row {i} outcome/identity invalid") from exc
        if bf <= 0 or k < 0 or k > bf or pitcher <= 0:
            raise PitcherKProbabilityModelError(f"row {i} outcome/identity impossible")
        xs.append(vector)
        ks.append(k)
        bfs.append(bf)
        pitchers.append(pitcher)
        seasons.append(season)
    return _Design(
        x=np.asarray(xs, dtype=float),
        k=np.asarray(ks, dtype=float),
        bf=np.asarray(bfs, dtype=float),
        pitcher_ids=tuple(pitchers),
        seasons=tuple(seasons),
    )


def _standardize_fit(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    return (x - mean) / scale, mean, scale


def _standardize_apply(x: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    if mean.shape != (len(FEATURE_NAMES),) or scale.shape != (len(FEATURE_NAMES),):
        raise PitcherKProbabilityModelError("fit standardization shape mismatch")
    if np.any(~np.isfinite(mean)) or np.any(~np.isfinite(scale)) or np.any(scale <= 0):
        raise PitcherKProbabilityModelError("fit standardization invalid")
    return (x - mean) / scale


def _fit_ridge(rows: Sequence[Mapping[str, Any]], alpha: float) -> dict[str, Any]:
    alpha = _number(alpha, "alpha")
    if alpha not in RIDGE_GRID:
        raise PitcherKProbabilityModelError("alpha outside frozen grid")
    d = _design(rows)
    z, mean, scale = _standardize_fit(d.x)
    X = np.column_stack([np.ones(len(z)), z])
    beta = np.zeros(X.shape[1], dtype=float)
    penalty = np.zeros_like(beta)
    penalty[1:] = alpha
    converged = False
    iterations = 0
    for iterations in range(1, 101):
        eta = np.clip(X @ beta, -30.0, 30.0)
        p = 1.0 / (1.0 + np.exp(-eta))
        variance = np.maximum(d.bf * p * (1.0 - p), 1e-10)
        gradient = X.T @ (d.k - d.bf * p) - penalty * beta
        hessian = X.T @ (X * variance[:, None]) + np.diag(penalty)
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError as exc:
            raise PitcherKProbabilityModelError("ridge fit singular") from exc
        beta = beta + step
        if float(np.max(np.abs(step))) <= 1e-10:
            converged = True
            break
    if not converged:
        raise PitcherKProbabilityModelError("ridge fit did not converge")
    return {
        "alpha": float(alpha),
        "coefficients": beta.tolist(),
        "feature_mean": mean.tolist(),
        "feature_scale": scale.tolist(),
        "iterations": iterations,
        "converged": True,
        "training_rows": len(rows),
    }


def _predict_rate(rows: Sequence[Mapping[str, Any]], fit: Mapping[str, Any]) -> np.ndarray:
    d = _design(rows)
    try:
        beta = np.asarray(fit["coefficients"], dtype=float)
        mean = np.asarray(fit["feature_mean"], dtype=float)
        scale = np.asarray(fit["feature_scale"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise PitcherKProbabilityModelError("fit artifact incomplete") from exc
    if beta.shape != (len(FEATURE_NAMES) + 1,) or np.any(~np.isfinite(beta)):
        raise PitcherKProbabilityModelError("fit coefficient shape invalid")
    z = _standardize_apply(d.x, mean, scale)
    eta = np.clip(np.column_stack([np.ones(len(z)), z]) @ beta, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-eta))


def _projected_bf(row: Mapping[str, Any]) -> int:
    features = row.get("features") or {}
    value = _number(features.get("recent_mean_batters_faced"), "recent_mean_batters_faced")
    # BF is positive; floor(x + .5) makes the preregistered ROUND rule deterministic.
    n = int(floor(value + 0.5))
    if not 1 <= n <= 50:
        raise PitcherKProbabilityModelError("projected BF outside frozen [1,50]")
    return n


def _binomial_pmf(k: int, n: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    p = min(1.0 - 1e-12, max(1e-12, float(p)))
    return exp(
        lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
        + k * log(p) + (n - k) * log(1.0 - p)
    )


def _beta_binomial_pmf(k: int, n: int, p: float, concentration: float) -> float:
    if k < 0 or k > n:
        return 0.0
    c = _number(concentration, "concentration")
    if c not in CONCENTRATION_GRID:
        raise PitcherKProbabilityModelError("concentration outside frozen grid")
    p = min(1.0 - 1e-12, max(1e-12, float(p)))
    if c >= 100_000_000.0:
        return _binomial_pmf(k, n, p)
    a, b = p * c, (1.0 - p) * c
    return exp(
        lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
        + lgamma(k + a) + lgamma(n - k + b) - lgamma(n + a + b)
        + lgamma(a + b) - lgamma(a) - lgamma(b)
    )


def count_distribution(n: int, p: float, concentration: float) -> np.ndarray:
    probs = np.asarray([_beta_binomial_pmf(k, n, p, concentration) for k in range(n + 1)], dtype=float)
    total = float(probs.sum())
    if not isfinite(total) or total <= 0:
        raise PitcherKProbabilityModelError("count probability mass invalid")
    probs /= total
    return probs


def over_probabilities(n: int, p: float, concentration: float) -> np.ndarray:
    probs = count_distribution(n, p, concentration)
    support = np.arange(n + 1)
    return np.asarray([float(probs[support > line].sum()) for line in HALF_LINES], dtype=float)


def _row_predictions(rows: Sequence[Mapping[str, Any]], fit: Mapping[str, Any], concentration: float) -> list[np.ndarray]:
    rates = _predict_rate(rows, fit)
    return [
        over_probabilities(_projected_bf(row), float(rate), concentration)
        for row, rate in zip(rows, rates)
    ]


def _rps(pred: np.ndarray, y_k: int) -> float:
    target = (float(y_k) > np.asarray(HALF_LINES)).astype(float)
    return float(((pred - target) ** 2).sum())


def _mean_rps(rows: Sequence[Mapping[str, Any]], preds: Sequence[np.ndarray]) -> float:
    if len(rows) != len(preds) or not rows:
        raise PitcherKProbabilityModelError("RPS rows/predictions mismatch")
    return float(np.mean([_rps(p, int(row["y_k"])) for row, p in zip(rows, preds)]))


def select_development_candidate(
    training_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    train = _design(training_rows)
    valid = _design(validation_rows)
    if set(train.seasons) != {2023} or set(valid.seasons) != {2024}:
        raise PitcherKProbabilityModelError("frozen 2023 training / 2024 validation split required")
    scored: list[dict[str, Any]] = []
    fit_by_alpha: dict[float, dict[str, Any]] = {}
    for alpha in RIDGE_GRID:
        fit = _fit_ridge(training_rows, alpha)
        fit_by_alpha[alpha] = fit
        for concentration in CONCENTRATION_GRID:
            preds = _row_predictions(validation_rows, fit, concentration)
            scored.append({
                "alpha": alpha,
                "concentration": concentration,
                "validation_mean_rps": _mean_rps(validation_rows, preds),
            })
    scored.sort(key=lambda r: (r["validation_mean_rps"], -r["alpha"], -r["concentration"]))
    winner = scored[0]
    combined = list(training_rows) + list(validation_rows)
    final_fit = _fit_ridge(combined, float(winner["alpha"]))
    return {
        "schema": ARTIFACT_SCHEMA,
        "candidate_family": CANDIDATE_FAMILY,
        "status": "FROZEN_DEVELOPMENT_FIT",
        "training_only": True,
        "candidate_test_rows_seen": False,
        "sportsbook_prices_used": False,
        "training_seasons": [2023],
        "validation_seasons": [2024],
        "refit_seasons": [2023, 2024],
        "selected_alpha": float(winner["alpha"]),
        "selected_concentration": float(winner["concentration"]),
        "selection_validation_mean_rps": float(winner["validation_mean_rps"]),
        "grid_scores": scored,
        "fit": final_fit,
        "feature_names": list(FEATURE_NAMES),
        "authority": AUTHORITY,
        "model_p_eligible": False,
        "deployment": False,
    }


def predict_candidate(rows: Sequence[Mapping[str, Any]], artifact: Mapping[str, Any]) -> list[np.ndarray]:
    if not isinstance(artifact, Mapping) or artifact.get("schema") != ARTIFACT_SCHEMA:
        raise PitcherKProbabilityModelError("frozen fit artifact required")
    if artifact.get("status") != "FROZEN_DEVELOPMENT_FIT":
        raise PitcherKProbabilityModelError("fit artifact not frozen")
    if artifact.get("training_only") is not True or artifact.get("candidate_test_rows_seen") is not False:
        raise PitcherKProbabilityModelError("fit artifact contaminated by candidate test")
    if artifact.get("sportsbook_prices_used") is not False:
        raise PitcherKProbabilityModelError("sportsbook-contaminated fit forbidden")
    return _row_predictions(rows, artifact.get("fit") or {}, float(artifact["selected_concentration"]))


def _typical_metrics(rows: Sequence[Mapping[str, Any]], preds: Sequence[np.ndarray]) -> dict[str, float]:
    idx = [HALF_LINES.index(line) for line in TYPICAL_LINES]
    ps: list[float] = []
    ys: list[float] = []
    for row, pred in zip(rows, preds):
        for j in idx:
            ps.append(float(pred[j]))
            ys.append(1.0 if int(row["y_k"]) > HALF_LINES[j] else 0.0)
    p = np.clip(np.asarray(ps), 1e-9, 1 - 1e-9)
    y = np.asarray(ys)
    logloss = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = 0.0
    for b in range(10):
        mask = bins == b
        if mask.any():
            ece += float(mask.mean() * abs(p[mask].mean() - y[mask].mean()))
    return {"log_loss": logloss, "ece": ece}


def _cluster_bootstrap_rps_diff(
    rows: Sequence[Mapping[str, Any]],
    candidate: Sequence[np.ndarray],
    incumbent: Sequence[np.ndarray],
) -> dict[str, float]:
    by_pitcher: dict[int, list[float]] = {}
    for row, cand, base in zip(rows, candidate, incumbent):
        pid = int(row["pitcher_id"])
        diff = _rps(cand, int(row["y_k"])) - _rps(base, int(row["y_k"]))
        by_pitcher.setdefault(pid, []).append(diff)
    keys = sorted(by_pitcher)
    if not keys:
        raise PitcherKProbabilityModelError("no pitcher clusters")
    sums = np.asarray([sum(by_pitcher[k]) for k in keys], dtype=float)
    counts = np.asarray([len(by_pitcher[k]) for k in keys], dtype=float)
    point = float(sums.sum() / counts.sum())
    rng = np.random.default_rng(BOOT_SEED)
    boots = np.empty(BOOT_REPS, dtype=float)
    for i in range(BOOT_REPS):
        sample = rng.integers(0, len(keys), size=len(keys))
        boots[i] = float(sums[sample].sum() / counts[sample].sum())
    return {
        "diff": point,
        "lo": float(np.quantile(boots, 0.025)),
        "hi": float(np.quantile(boots, 0.975)),
        "pitchers": float(len(keys)),
        "starts": float(len(rows)),
    }


def evaluate_candidate_test(
    test_rows: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    design = _design(test_rows)
    if set(design.seasons) != {2025}:
        raise PitcherKProbabilityModelError("frozen 2025 candidate-test season required")
    if len(test_rows) < MIN_TEST_STARTS:
        raise PitcherKProbabilityModelError(f"candidate test requires at least {MIN_TEST_STARTS} starts")
    candidate = predict_candidate(test_rows, artifact)
    incumbent: list[np.ndarray] = []
    for i, row in enumerate(test_rows):
        raw = row.get("incumbent_p_over")
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != len(HALF_LINES):
            raise PitcherKProbabilityModelError(f"row {i} incumbent_p_over must align with frozen half-lines")
        arr = np.asarray([_number(v, f"row {i}.incumbent_p_over") for v in raw], dtype=float)
        if np.any((arr < 0) | (arr > 1)):
            raise PitcherKProbabilityModelError(f"row {i} incumbent probabilities outside [0,1]")
        incumbent.append(arr)

    boot = _cluster_bootstrap_rps_diff(test_rows, candidate, incumbent)
    cand_typical = _typical_metrics(test_rows, candidate)
    base_typical = _typical_metrics(test_rows, incumbent)
    rates = _predict_rate(test_rows, artifact.get("fit") or {})
    count_mae = float(np.mean([
        abs(_projected_bf(row) * float(rate) - int(row["y_k"]))
        for row, rate in zip(test_rows, rates)
    ]))
    rules = {
        "rps_ci_high_lt_0": boot["hi"] < 0.0,
        "typical_ece_lte_incumbent_plus_0_005": cand_typical["ece"] <= base_typical["ece"] + 0.005,
        "typical_log_loss_lte_incumbent": cand_typical["log_loss"] <= base_typical["log_loss"],
        "minimum_test_starts": len(test_rows) >= MIN_TEST_STARTS,
    }
    return {
        "schema": "MLB_PITCHER_K_PROBABILITY_CANDIDATE_TEST_V1",
        "candidate_family": CANDIDATE_FAMILY,
        "test_seasons": [2025],
        "candidate_mean_rps": _mean_rps(test_rows, candidate),
        "incumbent_mean_rps": _mean_rps(test_rows, incumbent),
        "rps_difference_bootstrap": boot,
        "candidate_typical": cand_typical,
        "incumbent_typical": base_typical,
        "candidate_count_mae": count_mae,
        "starts": len(test_rows),
        "unique_pitchers": len(set(design.pitcher_ids)),
        "pass_rules": rules,
        "development_pass": all(rules.values()),
        "authority": AUTHORITY,
        "model_p_eligible": False,
        "deployment": False,
        "promotion_authority": False,
    }
