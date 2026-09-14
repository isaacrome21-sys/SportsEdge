from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable


@dataclass(frozen=True)
class ProjectionObservation:
    player_id: str
    actual: float
    mean: float
    p10: float
    p50: float
    p90: float

    def validate(self) -> None:
        if not self.player_id.strip():
            raise ValueError("DFS_CALIBRATION_PLAYER_ID_REQUIRED")
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("DFS_CALIBRATION_QUANTILES_INVALID")


@dataclass(frozen=True)
class ProjectionCalibrationMetrics:
    observations: int
    mae: float
    rmse: float
    exceed_p10_rate: float
    exceed_p50_rate: float
    exceed_p90_rate: float
    central_80_coverage: float
    quantile_calibration_error: float

    def validate(self) -> None:
        if self.observations < 1:
            raise ValueError("DFS_CALIBRATION_OBSERVATIONS_INVALID")
        for value in (
            self.exceed_p10_rate,
            self.exceed_p50_rate,
            self.exceed_p90_rate,
            self.central_80_coverage,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("DFS_CALIBRATION_RATE_INVALID")
        if self.mae < 0.0 or self.rmse < 0.0 or self.quantile_calibration_error < 0.0:
            raise ValueError("DFS_CALIBRATION_ERROR_INVALID")


def evaluate_projection_calibration(
    observations: Iterable[ProjectionObservation],
) -> ProjectionCalibrationMetrics:
    rows = tuple(observations)
    if not rows:
        raise ValueError("DFS_CALIBRATION_OBSERVATIONS_EMPTY")
    for row in rows:
        row.validate()
    n = len(rows)
    errors = [row.actual - row.mean for row in rows]
    mae = sum(abs(x) for x in errors) / n
    rmse = sqrt(sum(x * x for x in errors) / n)
    exceed10 = sum(row.actual > row.p10 for row in rows) / n
    exceed50 = sum(row.actual > row.p50 for row in rows) / n
    exceed90 = sum(row.actual > row.p90 for row in rows) / n
    central80 = sum(row.p10 <= row.actual <= row.p90 for row in rows) / n
    calibration_error = (
        abs(exceed10 - 0.90)
        + abs(exceed50 - 0.50)
        + abs(exceed90 - 0.10)
        + abs(central80 - 0.80)
    ) / 4.0
    metrics = ProjectionCalibrationMetrics(
        observations=n,
        mae=mae,
        rmse=rmse,
        exceed_p10_rate=exceed10,
        exceed_p50_rate=exceed50,
        exceed_p90_rate=exceed90,
        central_80_coverage=central80,
        quantile_calibration_error=calibration_error,
    )
    metrics.validate()
    return metrics
