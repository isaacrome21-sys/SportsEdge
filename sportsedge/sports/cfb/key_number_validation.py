"""CFB key-margin calibration diagnostics.

The live simulator is already integer-valued. This module verifies whether its learned
residual distribution reproduces held-out key-margin mass before any explicit key-number
correction is permitted. No hand-tuned probability boosts are allowed.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence


class CFBKeyNumberError(ValueError):
    pass


def _margin(row: Mapping[str, Any]) -> int:
    if "margin" in row:
        value = float(row["margin"])
    else:
        value = float(row["home_score"]) - float(row["away_score"])
    if not isfinite(value):
        raise CFBKeyNumberError("MARGIN_NONFINITE")
    if abs(value - round(value)) > 1e-9:
        raise CFBKeyNumberError("MARGIN_NOT_INTEGER")
    return int(round(value))


@dataclass(frozen=True)
class KeyMarginRow:
    margin: int
    empirical_mass: float
    simulated_mass: float
    absolute_error: float
    within_tolerance: bool


@dataclass(frozen=True)
class KeyNumberCalibrationReport:
    n_empirical: int
    n_simulated: int
    tolerance: float
    rows: tuple[KeyMarginRow, ...]

    @property
    def passed(self) -> bool:
        return bool(self.rows) and all(row.within_tolerance for row in self.rows)

    def require_pass(self) -> "KeyNumberCalibrationReport":
        if not self.passed:
            failures = [str(row.margin) for row in self.rows if not row.within_tolerance]
            raise CFBKeyNumberError("KEY_NUMBER_CALIBRATION_FAILED:" + ",".join(failures))
        return self


def key_number_calibration_report(
    empirical_rows: Iterable[Mapping[str, Any]],
    simulated_rows: Iterable[Mapping[str, Any]],
    *,
    key_margins: Sequence[int] = (-7, -3, 3, 7),
    tolerance: float = 0.015,
) -> KeyNumberCalibrationReport:
    empirical = [_margin(row) for row in empirical_rows]
    simulated = [_margin(row) for row in simulated_rows]
    if not empirical or not simulated:
        raise CFBKeyNumberError("KEY_NUMBER_SAMPLE_REQUIRED")
    tol = float(tolerance)
    if not isfinite(tol) or not 0.0 <= tol < 1.0:
        raise CFBKeyNumberError("KEY_NUMBER_TOLERANCE_INVALID")
    keys = tuple(int(x) for x in key_margins)
    if not keys or len(keys) != len(set(keys)):
        raise CFBKeyNumberError("KEY_NUMBER_SET_INVALID")
    rows: list[KeyMarginRow] = []
    for margin in keys:
        empirical_mass = empirical.count(margin) / len(empirical)
        simulated_mass = simulated.count(margin) / len(simulated)
        error = abs(simulated_mass - empirical_mass)
        rows.append(KeyMarginRow(
            margin=margin,
            empirical_mass=empirical_mass,
            simulated_mass=simulated_mass,
            absolute_error=error,
            within_tolerance=error <= tol,
        ))
    return KeyNumberCalibrationReport(
        n_empirical=len(empirical),
        n_simulated=len(simulated),
        tolerance=tol,
        rows=tuple(rows),
    )


def fold_key_number_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    empirical_field: str = "empirical_distribution",
    simulated_field: str = "simulated_distribution",
    tolerance: float = 0.015,
) -> dict[int, KeyNumberCalibrationReport]:
    """Build one calibration report per held-out season/fold."""

    grouped: dict[int, dict[str, list[Mapping[str, Any]]]] = {}
    for row in rows:
        season = int(row["test_season"])
        bucket = grouped.setdefault(season, {"empirical": [], "simulated": []})
        empirical = row.get(empirical_field)
        simulated = row.get(simulated_field)
        if not isinstance(empirical, (list, tuple)) or not isinstance(simulated, (list, tuple)):
            raise CFBKeyNumberError("FOLD_DISTRIBUTION_REQUIRED")
        bucket["empirical"].extend(empirical)
        bucket["simulated"].extend(simulated)
    return {
        season: key_number_calibration_report(
            value["empirical"], value["simulated"], tolerance=tolerance,
        )
        for season, value in sorted(grouped.items())
    }
