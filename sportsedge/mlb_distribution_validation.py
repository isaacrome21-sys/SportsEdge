"""Outer-fold discrete-mass validation for MLB run distributions.

MLB totals and run lines are sensitive to clustered integer run totals and one-run
margins. This module compares held-out empirical mass with simulated mass and fails
closed when the pre-registered tolerance is exceeded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any


class MLBDistributionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class MassCalibrationPoint:
    key: int
    empirical_mass: float
    simulated_mass: float
    absolute_error: float


@dataclass(frozen=True)
class MLBDistributionCalibrationReport:
    statistic: str
    tolerance: float
    points: tuple[MassCalibrationPoint, ...]

    @property
    def max_absolute_error(self) -> float:
        return max((point.absolute_error for point in self.points), default=0.0)

    @property
    def passed(self) -> bool:
        return bool(self.points) and self.max_absolute_error <= self.tolerance + 1e-15

    def require_pass(self) -> "MLBDistributionCalibrationReport":
        if not self.passed:
            raise MLBDistributionValidationError(
                f"MLB_DISTRIBUTION_MASS_CALIBRATION_FAILED:{self.statistic}:"
                f"error={self.max_absolute_error:.8f}:tolerance={self.tolerance:.8f}"
            )
        return self


def _mass(values: list[int], key: int) -> float:
    if not values:
        raise MLBDistributionValidationError("DISTRIBUTION_ROWS_REQUIRED")
    return sum(value == key for value in values) / len(values)


def _extract(rows: Iterable[Mapping[str, Any]], statistic: str) -> list[int]:
    out: list[int] = []
    for row in rows:
        if statistic == "TOTAL_RUNS":
            if "total_runs" in row:
                value = row["total_runs"]
            elif "home_runs" in row and "away_runs" in row:
                value = int(row["home_runs"]) + int(row["away_runs"])
            else:
                raise MLBDistributionValidationError("TOTAL_RUNS_FIELDS_REQUIRED")
        elif statistic == "GAME_MARGIN":
            if "game_margin" in row:
                value = row["game_margin"]
            elif "home_runs" in row and "away_runs" in row:
                value = int(row["home_runs"]) - int(row["away_runs"])
            else:
                raise MLBDistributionValidationError("GAME_MARGIN_FIELDS_REQUIRED")
        else:
            raise MLBDistributionValidationError("DISTRIBUTION_STATISTIC_INVALID")
        if isinstance(value, bool):
            raise MLBDistributionValidationError("DISTRIBUTION_VALUE_INTEGER_REQUIRED")
        integer = int(value)
        if float(value) != float(integer):
            raise MLBDistributionValidationError("DISTRIBUTION_VALUE_INTEGER_REQUIRED")
        out.append(integer)
    if not out:
        raise MLBDistributionValidationError("DISTRIBUTION_ROWS_REQUIRED")
    return out


def calibration_report(
    empirical_rows: Iterable[Mapping[str, Any]],
    simulated_rows: Iterable[Mapping[str, Any]],
    *,
    statistic: str,
    keys: Iterable[int],
    tolerance: float = 0.015,
) -> MLBDistributionCalibrationReport:
    limit = float(tolerance)
    if not 0.0 <= limit <= 1.0:
        raise MLBDistributionValidationError("DISTRIBUTION_TOLERANCE_RANGE")
    empirical = _extract(empirical_rows, statistic)
    simulated = _extract(simulated_rows, statistic)
    points = []
    for key in tuple(int(x) for x in keys):
        empirical_mass = _mass(empirical, key)
        simulated_mass = _mass(simulated, key)
        points.append(MassCalibrationPoint(
            key=key,
            empirical_mass=empirical_mass,
            simulated_mass=simulated_mass,
            absolute_error=abs(empirical_mass - simulated_mass),
        ))
    if not points:
        raise MLBDistributionValidationError("DISTRIBUTION_KEYS_REQUIRED")
    return MLBDistributionCalibrationReport(str(statistic), limit, tuple(points))


def total_runs_calibration_report(empirical_rows, simulated_rows, *, tolerance: float = 0.015):
    return calibration_report(
        empirical_rows,
        simulated_rows,
        statistic="TOTAL_RUNS",
        keys=(7, 8, 9),
        tolerance=tolerance,
    )


def run_line_margin_calibration_report(empirical_rows, simulated_rows, *, tolerance: float = 0.015):
    return calibration_report(
        empirical_rows,
        simulated_rows,
        statistic="GAME_MARGIN",
        keys=(-1, 1),
        tolerance=tolerance,
    )
