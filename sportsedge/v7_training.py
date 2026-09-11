from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from math import exp, log, sqrt
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from .source_lineage import canonical_json_sha256
from .v7_baseball_features import assert_no_market_contamination
from .v7_candidate import build_candidate_artifact, load_candidate, score_candidate
from .v7_feature_bundle import (
    V7_COMBINED_FEATURE_CONTRACT_SHA256,
    V7_MODEL_FEATURE_PATHS,
    get_numeric_path,
)
from .v7_validation import score_fold

V7_TRAINING_VERSION = "mlb_v7_training_v1"


class V7TrainingError(ValueError):
    pass


@dataclass(frozen=True)
class TrainingReport:
    model_name: str
    train_n: int
    calibration_n: int
    train_end: str
    calibration_start: str
    calibration_end: str
    holdout_start: str
    iterations: int
    l2: float
    learning_rate: float
    calibration_intercept_delta: float
    candidate_sha256: str
    feature_contract_sha256: str
    report_sha256: str


def _date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except Exception as exc:
        raise V7TrainingError(f"invalid {field}") from exc


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + exp(-z))
    ez = exp(z)
    return ez / (1.0 + ez)


def _label(row: Mapping[str, Any], key: str) -> int:
    try:
        y = int(row[key])
    except Exception as exc:
        raise V7TrainingError(f"missing/invalid {key}") from exc
    if y not in {0, 1}:
        raise V7TrainingError(f"{key} must be 0/1")
    return y


def _vector_for_contract(payload: Mapping[str, Any], *, feature_paths: Sequence[str], feature_contract_sha256: str) -> dict[str, float]:
    if str(payload.get("feature_contract_sha256") or "") != str(feature_contract_sha256):
        raise V7TrainingError("feature payload contract hash mismatch")
    assert_no_market_contamination(payload)
    return {path: get_numeric_path(payload, path) for path in feature_paths}


def _matrix(rows: Sequence[Mapping[str, Any]], feature_paths: Sequence[str], label_key: str, *, feature_contract_sha256: str) -> tuple[list[list[float]], list[int]]:
    x: list[list[float]] = []
    y: list[int] = []
    for row in rows:
        payload = row.get("feature_payload")
        if not isinstance(payload, Mapping):
            raise V7TrainingError("feature_payload required")
        vector = _vector_for_contract(payload, feature_paths=feature_paths, feature_contract_sha256=feature_contract_sha256)
        x.append([vector[p] for p in feature_paths])
        y.append(_label(row, label_key))
    return x, y


def _fit_standardized_logit(x: Sequence[Sequence[float]], y: Sequence[int], *, l2: float, iterations: int, learning_rate: float) -> tuple[float, list[float]]:
    if not x or len(x) != len(y): raise V7TrainingError("non-empty paired training matrix required")
    n, p = len(x), len(x[0])
    if p == 0 or any(len(row) != p for row in x): raise V7TrainingError("invalid training matrix shape")
    if n < 10: raise V7TrainingError("at least 10 training rows required")
    if not 0 <= float(l2) < 1e6 or int(iterations) <= 0 or not 0 < float(learning_rate) <= 1: raise V7TrainingError("invalid optimizer settings")
    means = [mean(row[j] for row in x) for j in range(p)]
    scales = []
    for j in range(p):
        variance = mean((row[j] - means[j]) ** 2 for row in x)
        scales.append(sqrt(variance) if variance > 1e-12 else 1.0)
    zmat = [[(row[j] - means[j]) / scales[j] for j in range(p)] for row in x]
    prevalence = min(1 - 1e-6, max(1e-6, mean(y)))
    intercept = log(prevalence / (1 - prevalence))
    beta = [0.0] * p
    lr, penalty = float(learning_rate), float(l2)
    for _ in range(int(iterations)):
        errors = [_sigmoid(intercept + sum(b * v for b, v in zip(beta, row))) - target for row, target in zip(zmat, y)]
        grad_i = sum(errors) / n
        grad_b = [sum(err * row[j] for err, row in zip(errors, zmat)) / n + penalty * beta[j] / n for j in range(p)]
        intercept -= lr * grad_i
        beta = [b - lr * g for b, g in zip(beta, grad_b)]
    raw_beta = [beta[j] / scales[j] for j in range(p)]
    raw_intercept = intercept - sum(beta[j] * means[j] / scales[j] for j in range(p))
    return raw_intercept, raw_beta


def _calibration_delta(logits: Sequence[float], outcomes: Sequence[int]) -> float:
    if not logits or len(logits) != len(outcomes): raise V7TrainingError("paired calibration rows required")
    target = mean(outcomes)
    lo, hi = -30.0, 30.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        predicted = mean(_sigmoid(z + mid) for z in logits)
        if predicted < target: lo = mid
        else: hi = mid
    return (lo + hi) / 2.0


def train_chronological_candidate(rows: Iterable[Mapping[str, Any]], *, model_name: str, train_end: Any, calibration_start: Any, calibration_end: Any, holdout_start: Any, date_key: str = "game_date", label_key: str = "outcome", feature_paths: Sequence[str] = V7_MODEL_FEATURE_PATHS, feature_contract_sha256: str = V7_COMBINED_FEATURE_CONTRACT_SHA256, l2: float = 1.0, iterations: int = 1200, learning_rate: float = 0.05) -> tuple[dict[str, Any], dict[str, Any]]:
    train_end_d, cal_start_d, cal_end_d, holdout_start_d = _date(train_end, "train_end"), _date(calibration_start, "calibration_start"), _date(calibration_end, "calibration_end"), _date(holdout_start, "holdout_start")
    if not (train_end_d < cal_start_d <= cal_end_d < holdout_start_d): raise V7TrainingError("chronology contract violation")
    if not feature_paths or len(feature_paths) != len(set(feature_paths)): raise V7TrainingError("feature_paths must be non-empty and unique")
    if not isinstance(feature_contract_sha256, str) or len(feature_contract_sha256) != 64: raise V7TrainingError("feature_contract_sha256 must be a 64-character hash")
    ordered = sorted(list(rows), key=lambda r: _date(r.get(date_key), date_key))
    train_rows = [r for r in ordered if _date(r.get(date_key), date_key) <= train_end_d]
    cal_rows = [r for r in ordered if cal_start_d <= _date(r.get(date_key), date_key) <= cal_end_d]
    if any(_date(r.get(date_key), date_key) >= holdout_start_d for r in train_rows + cal_rows): raise V7TrainingError("holdout contamination detected")
    if len(cal_rows) < 2: raise V7TrainingError("at least two calibration rows required")
    x, y = _matrix(train_rows, feature_paths, label_key, feature_contract_sha256=feature_contract_sha256)
    intercept, betas = _fit_standardized_logit(x, y, l2=l2, iterations=iterations, learning_rate=learning_rate)
    coefficients = {path: beta for path, beta in zip(feature_paths, betas)}
    provisional = build_candidate_artifact(model_name=model_name, feature_contract_sha256=feature_contract_sha256, intercept=intercept, coefficients=coefficients)
    loaded = load_candidate(provisional)
    cal_logits, cal_y = [], []
    for row in cal_rows:
        payload = row["feature_payload"]
        vector = _vector_for_contract(payload, feature_paths=feature_paths, feature_contract_sha256=feature_contract_sha256)
        cal_logits.append(loaded.intercept + sum(loaded.coefficients[p] * vector[p] for p in feature_paths))
        cal_y.append(_label(row, label_key))
    delta = _calibration_delta(cal_logits, cal_y)
    artifact = build_candidate_artifact(model_name=model_name, feature_contract_sha256=feature_contract_sha256, intercept=intercept + delta, coefficients=coefficients)
    candidate = load_candidate(artifact)
    cal_probs = [score_candidate(candidate, row["feature_payload"]) for row in cal_rows]
    metrics = score_fold(name="calibration", probabilities=cal_probs, outcomes=cal_y)
    base_report = {"training_version": V7_TRAINING_VERSION, "model_name": str(model_name), "train_n": len(train_rows), "calibration_n": len(cal_rows), "train_end": train_end_d.isoformat(), "calibration_start": cal_start_d.isoformat(), "calibration_end": cal_end_d.isoformat(), "holdout_start": holdout_start_d.isoformat(), "iterations": int(iterations), "l2": float(l2), "learning_rate": float(learning_rate), "calibration_intercept_delta": delta, "candidate_sha256": candidate.candidate_sha256, "feature_contract_sha256": candidate.feature_contract_sha256, "feature_paths": list(feature_paths), "calibration_metrics": asdict(metrics), "fit_max_date": max(_date(r.get(date_key), date_key) for r in train_rows + cal_rows).isoformat(), "sportsbook_data_used": False}
    report = dict(base_report)
    report["report_sha256"] = canonical_json_sha256(base_report)
    return artifact, report


def evaluate_frozen_candidate(artifact: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], *, label_key: str = "outcome", name: str = "holdout") -> dict[str, Any]:
    candidate = load_candidate(artifact)
    material = list(rows)
    probs = [score_candidate(candidate, row["feature_payload"]) for row in material]
    outcomes = [_label(row, label_key) for row in material]
    metrics = score_fold(name=name, probabilities=probs, outcomes=outcomes)
    result = {"candidate_sha256": candidate.candidate_sha256, "metrics": asdict(metrics)}
    result["evaluation_sha256"] = canonical_json_sha256(result)
    return result
