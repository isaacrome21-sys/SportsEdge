"""Chronological evaluation for the NBA pace/efficiency baseline.

Metrics are descriptive holdout diagnostics only. They do not promote a model,
create a probability, or claim betting performance.
"""
from dataclasses import dataclass
import math
from statistics import fmean
from typing import Iterable

from .pace_efficiency import NBAPaceEfficiencyModel, predict_state
from .training import NBATrainingRow, training_digest


@dataclass(frozen=True)
class NBAHoldoutEvaluation:
    games: int
    home_mae: float
    away_mae: float
    margin_mae: float
    total_mae: float
    validation_sha256: str
    model_version: str


def evaluate_holdout(model: NBAPaceEfficiencyModel, rows: Iterable[NBATrainingRow]) -> NBAHoldoutEvaluation:
    data=tuple(sorted(rows,key=lambda r:(r.tipoff,r.game_id)))
    if not data:
        raise ValueError("validation rows are required")
    home=[]; away=[]; margin=[]; total=[]
    for r in data:
        r.validate()
        p=predict_state(model,r)
        hp=p["expected_possessions"]*p["home_points_per_100"]/100.0
        ap=p["expected_possessions"]*p["away_points_per_100"]/100.0
        if not all(math.isfinite(x) for x in (hp,ap)):
            raise ValueError("non-finite holdout prediction")
        home.append(abs(hp-r.home_points)); away.append(abs(ap-r.away_points))
        margin.append(abs((hp-ap)-(r.home_points-r.away_points)))
        total.append(abs((hp+ap)-(r.home_points+r.away_points)))
    return NBAHoldoutEvaluation(len(data),fmean(home),fmean(away),fmean(margin),fmean(total),training_digest(data),model.version)
