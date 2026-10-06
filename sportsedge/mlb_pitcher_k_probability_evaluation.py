"""Season-bound development and one-look evaluation for the frozen MLB pitcher-K candidate.

This module layers the #1763 preregistered 2023/2024/2025 boundaries and metrics
over the candidate implementation merged in #1766.  It does not acquire rows or
execute the candidate-test look by itself.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite, log
from typing import Any, Mapping, Sequence

import numpy as np

from .mlb_pitcher_k_probability_candidate import (
    AUTHORITY,
    CANDIDATE_FAMILY,
    HALF_LINES,
    PitcherKProbabilityCandidateError,
    PitcherKRateFit,
    fit_payload,
    fit_rate_model,
    predict_k_rate,
    price_threshold,
    projected_batters_faced,
    select_hyperparameters,
)

DEVELOPMENT_SCHEMA = "MLB_PITCHER_K_DEVELOPMENT_FIT_V1"
EVALUATION_SCHEMA = "MLB_PITCHER_K_CANDIDATE_TEST_V1"
TRAINING_SEASON = 2023
VALIDATION_SEASON = 2024
TEST_SEASON = 2025
TYPICAL_LINES = (3.5, 4.5, 5.5, 6.5)
MIN_TEST_STARTS = 500
BOOT_REPS = 2000
BOOT_SEED = 20261006


class PitcherKProbabilityEvaluationError(ValueError):
    pass


def _season(row: Mapping[str, Any], index: int) -> int:
    try:
        return int(row["season"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError(f"row {index}.season required") from exc


def _require_season(rows: Sequence[Mapping[str, Any]], season: int, name: str) -> None:
    if not rows:
        raise PitcherKProbabilityEvaluationError(f"{name} rows required")
    bad = [i for i, row in enumerate(rows) if _season(row, i) != season]
    if bad:
        raise PitcherKProbabilityEvaluationError(
            f"{name} must contain only frozen season {season}; first mismatch row {bad[0]}"
        )


def _digest(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def build_development_fit(
    training_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Select on 2024, then refit the chosen ridge alpha on 2023+2024 only."""
    _require_season(training_rows, TRAINING_SEASON, "training")
    _require_season(validation_rows, VALIDATION_SEASON, "validation")
    selected = select_hyperparameters(training_rows, validation_rows)
    alpha = float(selected["ridge_alpha"])
    concentration = float(selected["concentration"])
    final_fit = fit_rate_model(list(training_rows) + list(validation_rows), ridge_alpha=alpha)
    payload = {
        "schema": DEVELOPMENT_SCHEMA,
        "candidate_family": CANDIDATE_FAMILY,
        "status": "FROZEN_DEVELOPMENT_FIT",
        "training_seasons": [TRAINING_SEASON],
        "validation_seasons": [VALIDATION_SEASON],
        "refit_seasons": [TRAINING_SEASON, VALIDATION_SEASON],
        "training_rows": len(training_rows),
        "validation_rows": len(validation_rows),
        "selected_ridge_alpha": alpha,
        "selected_concentration": concentration,
        "selection_mean_rps": float(selected["mean_rps"]),
        "selection_grid_scores": selected["grid_scores"],
        "rate_fit": fit_payload(final_fit),
        "candidate_test_rows_seen": False,
        "sportsbook_prices_used": False,
        "market_consensus_used": False,
        "authority": AUTHORITY,
        "model_p_eligible": False,
        "deployment": False,
        "promotion_authority": False,
    }
    payload["development_fit_sha256"] = _digest(payload)
    return payload


def _fit_from_artifact(artifact: Mapping[str, Any]) -> tuple[PitcherKRateFit, float]:
    if not isinstance(artifact, Mapping) or artifact.get("schema") != DEVELOPMENT_SCHEMA:
        raise PitcherKProbabilityEvaluationError("development fit artifact required")
    if artifact.get("status") != "FROZEN_DEVELOPMENT_FIT":
        raise PitcherKProbabilityEvaluationError("development fit is not frozen")
    if artifact.get("candidate_family") != CANDIDATE_FAMILY:
        raise PitcherKProbabilityEvaluationError("candidate family mismatch")
    if artifact.get("training_seasons") != [TRAINING_SEASON] or artifact.get("validation_seasons") != [VALIDATION_SEASON]:
        raise PitcherKProbabilityEvaluationError("development season identity changed")
    if artifact.get("refit_seasons") != [TRAINING_SEASON, VALIDATION_SEASON]:
        raise PitcherKProbabilityEvaluationError("refit season identity changed")
    if artifact.get("candidate_test_rows_seen") is not False:
        raise PitcherKProbabilityEvaluationError("development fit saw candidate-test rows")
    if artifact.get("sportsbook_prices_used") is not False or artifact.get("market_consensus_used") is not False:
        raise PitcherKProbabilityEvaluationError("market-contaminated fit forbidden")
    if artifact.get("model_p_eligible") is not False or artifact.get("deployment") is not False:
        raise PitcherKProbabilityEvaluationError("development artifact cannot be deployable")
    expected = dict(artifact)
    supplied_digest = str(expected.pop("development_fit_sha256", ""))
    if len(supplied_digest) != 64 or supplied_digest != _digest(expected):
        raise PitcherKProbabilityEvaluationError("development fit digest mismatch")
    raw = artifact.get("rate_fit")
    if not isinstance(raw, Mapping):
        raise PitcherKProbabilityEvaluationError("rate fit payload required")
    try:
        fit = PitcherKRateFit(
            candidate_family=str(raw["candidate_family"]),
            feature_names=tuple(raw["feature_names"]),
            means=tuple(float(v) for v in raw["means"]),
            scales=tuple(float(v) for v in raw["scales"]),
            coefficients=tuple(float(v) for v in raw["coefficients"]),
            ridge_alpha=float(raw["ridge_alpha"]),
            training_rows=int(raw["training_rows"]),
            training_batters_faced=int(raw["training_batters_faced"]),
            fit_sha256=str(raw["fit_sha256"]),
        )
        concentration = float(artifact["selected_concentration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError("development fit payload malformed") from exc
    if not isfinite(concentration) or concentration <= 0:
        raise PitcherKProbabilityEvaluationError("selected concentration invalid")
    return fit, concentration


def candidate_over_vector(
    row: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> np.ndarray:
    fit, concentration = _fit_from_artifact(artifact)
    candidate = row.get("candidate")
    if not isinstance(candidate, Mapping):
        raise PitcherKProbabilityEvaluationError("row candidate required")
    try:
        return np.asarray([
            price_threshold(candidate, fit, concentration=concentration, line=line)["candidate_p_over"]
            for line in HALF_LINES
        ], dtype=float)
    except PitcherKProbabilityCandidateError as exc:
        raise PitcherKProbabilityEvaluationError(str(exc)) from exc


def _realized_k(row: Mapping[str, Any], index: int) -> int:
    try:
        value = int(row["realized_strikeouts"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError(f"row {index}.realized_strikeouts required") from exc
    if value < 0:
        raise PitcherKProbabilityEvaluationError(f"row {index}.realized_strikeouts invalid")
    return value


def _pitcher_id(row: Mapping[str, Any], index: int) -> int:
    try:
        value = int(row["pitcher_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError(f"row {index}.pitcher_id required") from exc
    if value <= 0:
        raise PitcherKProbabilityEvaluationError(f"row {index}.pitcher_id invalid")
    return value


def _incumbent_vector(row: Mapping[str, Any], index: int) -> np.ndarray:
    raw = row.get("incumbent_p_over")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != len(HALF_LINES):
        raise PitcherKProbabilityEvaluationError(
            f"row {index}.incumbent_p_over must align with frozen half-lines"
        )
    try:
        out = np.asarray([float(v) for v in raw], dtype=float)
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError(f"row {index}.incumbent_p_over invalid") from exc
    if np.any(~np.isfinite(out)) or np.any((out < 0) | (out > 1)):
        raise PitcherKProbabilityEvaluationError(f"row {index}.incumbent probabilities outside [0,1]")
    return out


def _rps(pred: np.ndarray, realized_k: int) -> float:
    target = (float(realized_k) > np.asarray(HALF_LINES)).astype(float)
    return float(np.mean((pred - target) ** 2))


def _typical_metrics(
    rows: Sequence[Mapping[str, Any]],
    predictions: Sequence[np.ndarray],
) -> dict[str, float]:
    indices = [HALF_LINES.index(line) for line in TYPICAL_LINES]
    ps: list[float] = []
    ys: list[float] = []
    for i, (row, pred) in enumerate(zip(rows, predictions)):
        yk = _realized_k(row, i)
        for j in indices:
            ps.append(float(pred[j]))
            ys.append(1.0 if yk > HALF_LINES[j] else 0.0)
    p = np.clip(np.asarray(ps, dtype=float), 1e-9, 1.0 - 1e-9)
    y = np.asarray(ys, dtype=float)
    ll = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = 0.0
    for b in range(10):
        mask = bins == b
        if mask.any():
            ece += float(mask.mean() * abs(float(p[mask].mean()) - float(y[mask].mean())))
    return {"log_loss": ll, "ece": ece, "observations": len(ps)}


def _cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    differences: Sequence[float],
) -> dict[str, float]:
    clusters: dict[int, list[float]] = {}
    for i, (row, value) in enumerate(zip(rows, differences)):
        clusters.setdefault(_pitcher_id(row, i), []).append(float(value))
    if not clusters:
        raise PitcherKProbabilityEvaluationError("pitcher clusters required")
    keys = sorted(clusters)
    sums = np.asarray([sum(clusters[k]) for k in keys], dtype=float)
    counts = np.asarray([len(clusters[k]) for k in keys], dtype=float)
    point = float(sums.sum() / counts.sum())
    rng = np.random.default_rng(BOOT_SEED)
    index = rng.integers(0, len(keys), size=(BOOT_REPS, len(keys)))
    boot = sums[index].sum(axis=1) / counts[index].sum(axis=1)
    return {
        "diff": point,
        "lo": float(np.quantile(boot, 0.025)),
        "hi": float(np.quantile(boot, 0.975)),
        "clusters": len(keys),
        "starts": len(rows),
        "reps": BOOT_REPS,
        "seed": BOOT_SEED,
    }


def evaluate_candidate_test(
    test_rows: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the preregistered one-look candidate-specific 2025 comparison."""
    _require_season(test_rows, TEST_SEASON, "candidate test")
    if len(test_rows) < MIN_TEST_STARTS:
        raise PitcherKProbabilityEvaluationError(
            f"candidate test requires at least {MIN_TEST_STARTS} eligible starts"
        )
    fit, _ = _fit_from_artifact(artifact)

    candidate: list[np.ndarray] = []
    incumbent: list[np.ndarray] = []
    diffs: list[float] = []
    abs_count_errors: list[float] = []
    for i, row in enumerate(test_rows):
        cand = candidate_over_vector(row, artifact)
        base = _incumbent_vector(row, i)
        yk = _realized_k(row, i)
        candidate.append(cand)
        incumbent.append(base)
        diffs.append(_rps(cand, yk) - _rps(base, yk))
        candidate_obj = row.get("candidate")
        if not isinstance(candidate_obj, Mapping):
            raise PitcherKProbabilityEvaluationError(f"row {i}.candidate required")
        try:
            expected_k = projected_batters_faced(candidate_obj) * predict_k_rate(fit, candidate_obj)
        except PitcherKProbabilityCandidateError as exc:
            raise PitcherKProbabilityEvaluationError(str(exc)) from exc
        abs_count_errors.append(abs(float(expected_k) - yk))

    candidate_rps = float(np.mean([_rps(p, _realized_k(row, i)) for i, (row, p) in enumerate(zip(test_rows, candidate))]))
    incumbent_rps = float(np.mean([_rps(p, _realized_k(row, i)) for i, (row, p) in enumerate(zip(test_rows, incumbent))]))
    cand_typical = _typical_metrics(test_rows, candidate)
    base_typical = _typical_metrics(test_rows, incumbent)
    bootstrap = _cluster_bootstrap(test_rows, diffs)
    rules = {
        "candidate_rps_minus_incumbent_ci_high_lt_0": bootstrap["hi"] < 0.0,
        "candidate_typical_ece_lte_incumbent_plus_0_005": cand_typical["ece"] <= base_typical["ece"] + 0.005,
        "candidate_typical_log_loss_lte_incumbent": cand_typical["log_loss"] <= base_typical["log_loss"],
        "minimum_candidate_test_starts": len(test_rows) >= MIN_TEST_STARTS,
    }
    report = {
        "schema": EVALUATION_SCHEMA,
        "candidate_family": CANDIDATE_FAMILY,
        "development_fit_sha256": artifact["development_fit_sha256"],
        "candidate_test_seasons": [TEST_SEASON],
        "candidate_test_rows": len(test_rows),
        "unique_pitchers": len({_pitcher_id(row, i) for i, row in enumerate(test_rows)}),
        "candidate_mean_rps": candidate_rps,
        "incumbent_mean_rps": incumbent_rps,
        "rps_difference_bootstrap": bootstrap,
        "candidate_typical": cand_typical,
        "incumbent_typical": base_typical,
        "candidate_count_mae": float(np.mean(abs_count_errors)),
        "pass_rules": rules,
        "development_pass": all(rules.values()),
        "candidate_test_is_broader_promotion_evidence": False,
        "authority": AUTHORITY,
        "model_p_eligible": False,
        "deployment": False,
        "promotion_authority": False,
    }
    report["readout_sha256"] = _digest(report)
    return report
