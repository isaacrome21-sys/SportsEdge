from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence


class MLBCalibrationSafetyError(ValueError):
    pass


def _prob(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise MLBCalibrationSafetyError(f"{field} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBCalibrationSafetyError(f"{field} must be numeric") from exc
    if not math.isfinite(x) or not 0 <= x <= 1:
        raise MLBCalibrationSafetyError(f"{field} must be finite in [0,1]")
    return x


@dataclass(frozen=True)
class ShrinkageResult:
    raw_probability: float
    reference_probability: float
    sample_n: int
    reliability: float
    shrunk_probability: float


def shrink_probability(*, raw_probability: Any, reference_probability: Any,
                       sample_n: int, half_reliability_n: int = 200) -> ShrinkageResult:
    """Research-only empirical shrinkage toward a reference probability.

    Reliability is n/(n+k), so small samples cannot express extreme confidence.
    This is not a promoted calibrator; k must be selected on walk-forward evidence.
    """
    raw = _prob(raw_probability, "raw_probability")
    ref = _prob(reference_probability, "reference_probability")
    if sample_n < 0 or half_reliability_n <= 0:
        raise MLBCalibrationSafetyError("invalid sample size")
    reliability = sample_n / (sample_n + half_reliability_n)
    shrunk = ref + reliability * (raw - ref)
    return ShrinkageResult(raw, ref, sample_n, reliability, shrunk)


@dataclass(frozen=True)
class CalibrationSlopeCheck:
    n: int
    low_mean_p: float
    low_observed: float
    high_mean_p: float
    high_observed: float
    action: str


def edge_monotonicity_check(probabilities: Sequence[Any], outcomes: Sequence[Any], *, split: float = .5,
                            minimum_n: int = 100) -> CalibrationSlopeCheck:
    """Fail-safe diagnostic: higher predicted probabilities should realize higher event rates."""
    if len(probabilities) != len(outcomes) or not probabilities:
        raise MLBCalibrationSafetyError("probabilities/outcomes must align and be non-empty")
    ps = [_prob(v, "probability") for v in probabilities]
    ys = [int(v) for v in outcomes]
    if any(v not in (0, 1) for v in ys):
        raise MLBCalibrationSafetyError("outcomes must be binary")
    pairs = sorted(zip(ps, ys), key=lambda x: x[0])
    cut = max(1, min(len(pairs) - 1, int(len(pairs) * split)))
    low, high = pairs[:cut], pairs[cut:]
    low_p = sum(p for p, _ in low) / len(low)
    high_p = sum(p for p, _ in high) / len(high)
    low_y = sum(y for _, y in low) / len(low)
    high_y = sum(y for _, y in high) / len(high)
    if len(pairs) < minimum_n:
        action = "INSUFFICIENT_EVIDENCE"
    elif high_y <= low_y:
        action = "QUARANTINE_RESEARCH"
    else:
        action = "PASS"
    return CalibrationSlopeCheck(len(pairs), low_p, low_y, high_p, high_y, action)
