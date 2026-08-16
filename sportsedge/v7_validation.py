from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from math import log, sqrt
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from .source_lineage import canonical_json_sha256

V7_VALIDATION_VERSION = "mlb_v7_validation_v1"


class V7ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ChronologicalSplit:
    name: str
    train_end: str
    validation_start: str
    validation_end: str


@dataclass(frozen=True)
class FoldMetrics:
    name: str
    n: int
    brier: float
    log_loss: float
    calibration_z: float


def _date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except Exception as exc:
        raise V7ValidationError(f"invalid {field}") from exc


def _prob(value: Any) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError) as exc:
        raise V7ValidationError("probability must be numeric") from exc
    if not 0.0 < p < 1.0:
        raise V7ValidationError("probability must be strictly between 0 and 1")
    return p


def make_expanding_splits(
    *, first_train_end: Any, validation_starts: Sequence[Any], validation_ends: Sequence[Any]
) -> list[ChronologicalSplit]:
    if len(validation_starts) != len(validation_ends) or not validation_starts:
        raise V7ValidationError("paired non-empty validation windows required")
    train_end = _date(first_train_end, "first_train_end")
    out: list[ChronologicalSplit] = []
    previous_end = train_end
    for i, (start_raw, end_raw) in enumerate(zip(validation_starts, validation_ends), start=1):
        start = _date(start_raw, "validation_start")
        end = _date(end_raw, "validation_end")
        if start <= previous_end or end < start:
            raise V7ValidationError("chronological split overlap/order violation")
        out.append(ChronologicalSplit(
            name=f"fold_{i}", train_end=previous_end.isoformat(),
            validation_start=start.isoformat(), validation_end=end.isoformat(),
        ))
        previous_end = end
    return out


def verify_untouched_holdout(rows: Iterable[Mapping[str, Any]], *, holdout_start: Any, holdout_end: Any, fit_date_key: str = "fit_max_date") -> None:
    start = _date(holdout_start, "holdout_start")
    end = _date(holdout_end, "holdout_end")
    if end < start:
        raise V7ValidationError("invalid holdout range")
    for row in rows:
        if fit_date_key not in row:
            raise V7ValidationError(f"missing {fit_date_key}")
        fit_max = _date(row[fit_date_key], fit_date_key)
        if fit_max >= start:
            raise V7ValidationError("holdout contamination detected")


def score_fold(*, name: str, probabilities: Sequence[Any], outcomes: Sequence[Any]) -> FoldMetrics:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise V7ValidationError("paired non-empty probabilities/outcomes required")
    ps = [_prob(p) for p in probabilities]
    ys = [int(y) for y in outcomes]
    if any(y not in {0, 1} for y in ys):
        raise V7ValidationError("outcomes must be 0/1")
    n = len(ps)
    brier = mean((p-y) ** 2 for p, y in zip(ps, ys))
    eps = 1e-15
    ll = -mean(y * log(max(eps, p)) + (1-y) * log(max(eps, 1-p)) for p, y in zip(ps, ys))
    var = sum(p * (1-p) for p in ps)
    z = 0.0 if var <= 0 else (sum(ys) - sum(ps)) / sqrt(var)
    return FoldMetrics(name=str(name), n=n, brier=brier, log_loss=ll, calibration_z=z)


def summarize_walk_forward(folds: Sequence[FoldMetrics]) -> dict[str, Any]:
    if not folds:
        raise V7ValidationError("at least one fold required")
    total_n = sum(f.n for f in folds)
    if total_n <= 0:
        raise V7ValidationError("invalid fold sample size")
    summary = {
        "validation_version": V7_VALIDATION_VERSION,
        "folds": [asdict(f) for f in folds],
        "n": total_n,
        "weighted_brier": sum(f.brier * f.n for f in folds) / total_n,
        "weighted_log_loss": sum(f.log_loss * f.n for f in folds) / total_n,
        "max_abs_calibration_z": max(abs(f.calibration_z) for f in folds),
    }
    summary["summary_sha256"] = canonical_json_sha256(summary)
    return summary


def compare_candidate_to_baseline(*, candidate: FoldMetrics, baseline: FoldMetrics) -> dict[str, Any]:
    if candidate.n != baseline.n:
        raise V7ValidationError("candidate/baseline must be paired on identical rows")
    result = {
        "n": candidate.n,
        "brier_delta": candidate.brier - baseline.brier,
        "log_loss_delta": candidate.log_loss - baseline.log_loss,
        "candidate_calibration_z": candidate.calibration_z,
        "baseline_calibration_z": baseline.calibration_z,
    }
    result["comparison_sha256"] = canonical_json_sha256(result)
    return result
