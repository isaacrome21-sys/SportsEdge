"""Fit NBA pace correction only from genuine bound possession observations."""
from dataclasses import replace
from statistics import fmean
from typing import Iterable

from .pace_efficiency import NBAPaceEfficiencyModel, fit_pace_efficiency
from .possession_history import NBAPossessionObservation, bind_possession_targets, possession_digest
from .training import NBATrainingRow


def fit_pace_efficiency_with_possessions(
    rows: Iterable[NBATrainingRow],
    observations: Iterable[NBAPossessionObservation],
) -> NBAPaceEfficiencyModel:
    data = tuple(rows)
    obs = tuple(observations)
    base = fit_pace_efficiency(data)
    pairs = bind_possession_targets(data, obs)
    errors = [actual - row.expected_possessions for row, actual in pairs]
    bias = fmean(errors)
    digest = possession_digest(obs)
    return replace(
        base,
        pace_bias=bias,
        version=f"NBA_PACE_EFFICIENCY_OBS_V1:{digest[:12]}",
    )


def pace_holdout_mae(
    model: NBAPaceEfficiencyModel,
    rows: Iterable[NBATrainingRow],
    observations: Iterable[NBAPossessionObservation],
) -> float:
    pairs = bind_possession_targets(tuple(rows), tuple(observations))
    errors = [abs((row.expected_possessions + model.pace_bias) - actual) for row, actual in pairs]
    return fmean(errors)
