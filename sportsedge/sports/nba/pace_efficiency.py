"""Fit deterministic NBA pace/efficiency corrections from PIT-safe history.

This is deliberately a small auditable baseline: it learns residual corrections
to pregame pace and offense/defense features. It does not claim predictive quality
until evaluated on an untouched chronological validation set.
"""
from dataclasses import dataclass
import math
from statistics import fmean
from typing import Iterable

from .training import NBATrainingRow, training_digest


@dataclass(frozen=True)
class NBAPaceEfficiencyModel:
    pace_bias: float
    home_efficiency_bias: float
    away_efficiency_bias: float
    residual_sd_home: float
    residual_sd_away: float
    training_rows: int
    training_sha256: str
    version: str = "NBA_PACE_EFFICIENCY_BASELINE_V1"


def _pregame_efficiency(row: NBATrainingRow, *, home: bool) -> float:
    # Symmetric blend of the offense's pregame rating and opponent defense.
    return ((row.home_offensive_rating + row.away_defensive_rating) / 2.0
            if home else
            (row.away_offensive_rating + row.home_defensive_rating) / 2.0)


def fit_pace_efficiency(rows: Iterable[NBATrainingRow]) -> NBAPaceEfficiencyModel:
    data=tuple(rows)
    if len(data) < 2:
        raise ValueError("at least two PIT-safe training rows are required")
    for r in data: r.validate()
    pace_errors=[]; home_errors=[]; away_errors=[]
    for r in data:
        # Regulation possessions are not recoverable from score alone. The row's
        # expected_possessions is therefore a pregame feature, not a fitted target;
        # pace bias stays zero until a possession-target history lane is supplied.
        pace_errors.append(0.0)
        h=_pregame_efficiency(r,home=True)
        a=_pregame_efficiency(r,home=False)
        home_errors.append((100.0*r.home_points/r.expected_possessions)-h)
        away_errors.append((100.0*r.away_points/r.expected_possessions)-a)
    hb=fmean(home_errors); ab=fmean(away_errors)
    def rms(xs,bias):
        return math.sqrt(fmean((x-bias)**2 for x in xs))
    return NBAPaceEfficiencyModel(
        fmean(pace_errors),hb,ab,rms(home_errors,hb),rms(away_errors,ab),
        len(data),training_digest(data),
    )


def predict_state(model: NBAPaceEfficiencyModel, row: NBATrainingRow):
    row.validate()
    pace=row.expected_possessions + model.pace_bias
    if pace <= 0:
        raise ValueError("predicted possessions must be positive")
    return {
        "expected_possessions": pace,
        "home_points_per_100": _pregame_efficiency(row,home=True)+model.home_efficiency_bias,
        "away_points_per_100": _pregame_efficiency(row,home=False)+model.away_efficiency_bias,
        "home_residual_sd": model.residual_sd_home,
        "away_residual_sd": model.residual_sd_away,
        "model_version": model.version,
        "training_sha256": model.training_sha256,
    }
