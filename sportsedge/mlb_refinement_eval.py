from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any, Iterable, Mapping, Sequence


class MLBRefinementEvalError(ValueError):
    pass


def _prob(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise MLBRefinementEvalError(f"{field} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBRefinementEvalError(f"{field} must be numeric") from exc
    if not math.isfinite(x) or not 0.0 <= x <= 1.0:
        raise MLBRefinementEvalError(f"{field} must be finite in [0,1]")
    return x


def _binary(value: Any, field: str = "outcome") -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        x = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBRefinementEvalError(f"{field} must be binary") from exc
    if x not in (0, 1):
        raise MLBRefinementEvalError(f"{field} must be binary")
    return x


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    if not probabilities or len(probabilities) != len(outcomes):
        raise MLBRefinementEvalError("probabilities/outcomes must be non-empty and aligned")
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(probabilities)


def log_loss(probabilities: Sequence[float], outcomes: Sequence[int], *, epsilon: float = 1e-12) -> float:
    if not probabilities or len(probabilities) != len(outcomes):
        raise MLBRefinementEvalError("probabilities/outcomes must be non-empty and aligned")
    total = 0.0
    for p, y in zip(probabilities, outcomes):
        q = min(1.0 - epsilon, max(epsilon, p))
        total -= y * math.log(q) + (1 - y) * math.log(1.0 - q)
    return total / len(probabilities)


@dataclass(frozen=True)
class CalibrationBucket:
    lower: float
    upper: float
    n: int
    mean_probability: float | None
    observed_rate: float | None
    absolute_gap: float | None


@dataclass(frozen=True)
class ModelEvaluation:
    n: int
    brier: float
    logloss: float
    calibration_mae: float
    buckets: tuple[CalibrationBucket, ...]


def evaluate_probabilities(probabilities: Sequence[Any], outcomes: Sequence[Any], *, bucket_edges: Sequence[float] = (0.0, .2, .4, .6, .8, 1.0)) -> ModelEvaluation:
    probs = [_prob(v, "probability") for v in probabilities]
    ys = [_binary(v) for v in outcomes]
    if not probs or len(probs) != len(ys):
        raise MLBRefinementEvalError("probabilities/outcomes must be non-empty and aligned")
    edges = [float(v) for v in bucket_edges]
    if len(edges) < 2 or edges[0] != 0.0 or edges[-1] != 1.0 or any(b <= a for a, b in zip(edges, edges[1:])):
        raise MLBRefinementEvalError("bucket_edges must increase from 0 to 1")

    buckets: list[CalibrationBucket] = []
    weighted_gap = 0.0
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        idx = [j for j, p in enumerate(probs) if (lo <= p < hi) or (i == len(edges) - 2 and p == 1.0)]
        if not idx:
            buckets.append(CalibrationBucket(lo, hi, 0, None, None, None))
            continue
        mp = sum(probs[j] for j in idx) / len(idx)
        observed = sum(ys[j] for j in idx) / len(idx)
        gap = abs(mp - observed)
        weighted_gap += len(idx) * gap
        buckets.append(CalibrationBucket(lo, hi, len(idx), mp, observed, gap))

    return ModelEvaluation(
        n=len(probs),
        brier=brier_score(probs, ys),
        logloss=log_loss(probs, ys),
        calibration_mae=weighted_gap / len(probs),
        buckets=tuple(buckets),
    )


def _identity(row: Mapping[str, Any]) -> tuple[str, ...]:
    keys = ("game_id", "market", "entity_id", "side", "line", "as_of_utc")
    values = tuple(str(row.get(k, "")).strip() for k in keys)
    if not values[0] or not values[1]:
        raise MLBRefinementEvalError("row identity requires game_id and market")
    return values


@dataclass(frozen=True)
class PairedComparison:
    n: int
    baseline: ModelEvaluation
    candidate: ModelEvaluation
    brier_delta: float
    logloss_delta: float
    calibration_mae_delta: float


def compare_paired_rows(baseline_rows: Iterable[Mapping[str, Any]], candidate_rows: Iterable[Mapping[str, Any]], *, probability_key: str = "model_p", outcome_key: str = "outcome") -> PairedComparison:
    baseline = {_identity(r): r for r in baseline_rows}
    candidate = {_identity(r): r for r in candidate_rows}
    if set(baseline) != set(candidate):
        missing_candidate = sorted(set(baseline) - set(candidate))
        missing_baseline = sorted(set(candidate) - set(baseline))
        raise MLBRefinementEvalError(
            f"paired identities differ: missing_candidate={len(missing_candidate)} missing_baseline={len(missing_baseline)}"
        )
    if not baseline:
        raise MLBRefinementEvalError("paired rows must be non-empty")

    ids = sorted(baseline)
    outcomes: list[int] = []
    base_probs: list[float] = []
    cand_probs: list[float] = []
    for ident in ids:
        b, c = baseline[ident], candidate[ident]
        by = _binary(b.get(outcome_key))
        cy = _binary(c.get(outcome_key))
        if by != cy:
            raise MLBRefinementEvalError("paired outcome mismatch")
        outcomes.append(by)
        base_probs.append(_prob(b.get(probability_key), f"baseline.{probability_key}"))
        cand_probs.append(_prob(c.get(probability_key), f"candidate.{probability_key}"))

    base_eval = evaluate_probabilities(base_probs, outcomes)
    cand_eval = evaluate_probabilities(cand_probs, outcomes)
    return PairedComparison(
        n=len(ids),
        baseline=base_eval,
        candidate=cand_eval,
        brier_delta=cand_eval.brier - base_eval.brier,
        logloss_delta=cand_eval.logloss - base_eval.logloss,
        calibration_mae_delta=cand_eval.calibration_mae - base_eval.calibration_mae,
    )


@dataclass(frozen=True)
class AblationDecision:
    feature: str
    n: int
    action: str
    reason: str
    brier_delta_without_feature: float
    logloss_delta_without_feature: float
    calibration_delta_without_feature: float


def decide_ablation(*, feature: str, comparison_without_feature: PairedComparison, minimum_n: int = 200, tolerance: float = 1e-6) -> AblationDecision:
    """Decide whether a research feature should be kept or removed.

    `comparison_without_feature` compares the current research candidate (baseline)
    against an otherwise identical candidate with one feature removed (candidate).
    Negative deltas mean removing the feature improved the metric. No production
    configuration is changed here; this is an evidence-only recommendation.
    """
    name = str(feature or "").strip()
    if not name:
        raise MLBRefinementEvalError("feature is required")
    if minimum_n <= 0:
        raise MLBRefinementEvalError("minimum_n must be positive")
    c = comparison_without_feature
    if c.n < minimum_n:
        return AblationDecision(name, c.n, "INSUFFICIENT_EVIDENCE", f"need >= {minimum_n} paired rows", c.brier_delta, c.logloss_delta, c.calibration_mae_delta)

    improved_brier = c.brier_delta < -tolerance
    improved_logloss = c.logloss_delta < -tolerance
    worsened_brier = c.brier_delta > tolerance
    worsened_logloss = c.logloss_delta > tolerance

    if improved_brier and improved_logloss:
        action = "REMOVE"
        reason = "removing feature improves both paired Brier and log loss"
    elif worsened_brier and worsened_logloss:
        action = "KEEP"
        reason = "removing feature worsens both paired Brier and log loss"
    else:
        action = "RETEST"
        reason = "proper scoring metrics disagree or are within tolerance"
    return AblationDecision(name, c.n, action, reason, c.brier_delta, c.logloss_delta, c.calibration_mae_delta)


def as_report(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise MLBRefinementEvalError("report value must be a dataclass instance")
