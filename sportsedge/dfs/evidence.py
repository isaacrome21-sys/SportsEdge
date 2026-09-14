from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean, stdev
from typing import Iterable, Mapping

DEFAULT_QUANTILES = (0.10, 0.50, 0.90)


@dataclass(frozen=True)
class QuantileObservation:
    actual: float
    quantiles: Mapping[float, float]


@dataclass(frozen=True)
class QuantileCalibration:
    quantile: float
    n: int
    observed_cdf_rate: float
    target_cdf_rate: float
    ci_low_95: float
    ci_high_95: float
    calibrated: bool


@dataclass(frozen=True)
class DistributionCalibrationResult:
    status: str
    n: int
    quantiles: tuple[QuantileCalibration, ...]
    reason: str


@dataclass(frozen=True)
class RoiVetoResult:
    n_slates: int
    mean_roi: float | None
    upper_ci_95: float | None
    veto: bool
    reason: str


@dataclass(frozen=True)
class DfsEvidenceDecision:
    status: str
    calibration: DistributionCalibrationResult
    roi_veto: RoiVetoResult
    reason: str


def _wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n) / denom
    return max(0.0, center - half), min(1.0, center + half)


def evaluate_distribution_calibration(
    observations: Iterable[QuantileObservation],
    *,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
    min_trials: int = 500,
) -> DistributionCalibrationResult:
    """Gate the DFS distribution on player-level out-of-sample quantile coverage.

    For a calibrated q-quantile, roughly q of realized outcomes should land at or
    below the forecast. The target must fall inside a Wilson 95% interval. The gate
    is BLOCKED until enough player outcomes exist; contest ROI cannot override it.
    """

    rows = tuple(observations)
    if min_trials < 1:
        raise ValueError("DFS_CALIBRATION_MIN_TRIALS_INVALID")
    if any(q <= 0.0 or q >= 1.0 for q in quantiles):
        raise ValueError("DFS_CALIBRATION_QUANTILE_INVALID")
    if len(rows) < min_trials:
        return DistributionCalibrationResult(
            status="BLOCKED",
            n=len(rows),
            quantiles=(),
            reason=f"INSUFFICIENT_PLAYER_LEVEL_EVIDENCE:{len(rows)}:{min_trials}",
        )

    results: list[QuantileCalibration] = []
    for q in quantiles:
        missing = sum(1 for row in rows if q not in row.quantiles)
        if missing:
            return DistributionCalibrationResult(
                status="BLOCKED",
                n=len(rows),
                quantiles=tuple(results),
                reason=f"MISSING_QUANTILE_FORECAST:{q}:{missing}",
            )
        hits = sum(1 for row in rows if float(row.actual) <= float(row.quantiles[q]))
        rate = hits / len(rows)
        low, high = _wilson(hits, len(rows))
        results.append(
            QuantileCalibration(
                quantile=q,
                n=len(rows),
                observed_cdf_rate=rate,
                target_cdf_rate=q,
                ci_low_95=low,
                ci_high_95=high,
                calibrated=low <= q <= high,
            )
        )

    failed = tuple(item.quantile for item in results if not item.calibrated)
    if failed:
        return DistributionCalibrationResult(
            status="FAILED",
            n=len(rows),
            quantiles=tuple(results),
            reason="QUANTILE_MISCALIBRATION:" + ",".join(str(q) for q in failed),
        )
    return DistributionCalibrationResult(
        status="PASS",
        n=len(rows),
        quantiles=tuple(results),
        reason="PLAYER_LEVEL_DISTRIBUTION_CALIBRATED",
    )


def evaluate_roi_veto(
    slate_rois: Iterable[float],
    *,
    min_slates_for_veto: int = 30,
) -> RoiVetoResult:
    """Use contest ROI only as a one-sided harm veto, never as promotion evidence."""

    values = tuple(float(value) for value in slate_rois)
    if not values:
        return RoiVetoResult(0, None, None, False, "ROI_TELEMETRY_UNAVAILABLE")
    mean = fmean(values)
    if len(values) < min_slates_for_veto or len(values) < 2:
        return RoiVetoResult(
            len(values), mean, None, False, "ROI_TOO_NOISY_FOR_VETO"
        )
    se = stdev(values) / sqrt(len(values))
    upper = mean + 1.96 * se
    veto = upper < 0.0
    return RoiVetoResult(
        len(values),
        mean,
        upper,
        veto,
        "ROI_CLEAR_HARM_VETO" if veto else "ROI_NO_HARM_VETO",
    )


def evaluate_dfs_evidence(
    observations: Iterable[QuantileObservation],
    slate_rois: Iterable[float] = (),
    *,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
    min_trials: int = 500,
    min_slates_for_roi_veto: int = 30,
) -> DfsEvidenceDecision:
    calibration = evaluate_distribution_calibration(
        observations,
        quantiles=quantiles,
        min_trials=min_trials,
    )
    roi = evaluate_roi_veto(
        slate_rois,
        min_slates_for_veto=min_slates_for_roi_veto,
    )
    if calibration.status != "PASS":
        return DfsEvidenceDecision(
            status=calibration.status,
            calibration=calibration,
            roi_veto=roi,
            reason=calibration.reason,
        )
    if roi.veto:
        return DfsEvidenceDecision(
            status="FAILED",
            calibration=calibration,
            roi_veto=roi,
            reason=roi.reason,
        )
    return DfsEvidenceDecision(
        status="PASS",
        calibration=calibration,
        roi_veto=roi,
        reason="CALIBRATION_PASS_NO_ROI_HARM_VETO",
    )
