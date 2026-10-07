"""Temporal development validation for the NHL public-boxscore baseline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, lgamma, log, sqrt
from typing import Iterable

from .official_boxscore_source import NHLOfficialCompletedGame
from .public_baseline import (
    NHLBaselineTrainingRow,
    NHLPublicBaselineArtifact,
    build_baseline_training_rows,
    fit_public_baseline,
)


@dataclass(frozen=True)
class NHLPublicBaselineValidation:
    training_rows: int
    validation_rows: int
    team_goal_mae: float
    team_goal_rmse: float
    poisson_negative_log_likelihood: float
    mean_predicted_regulation_goals: float
    mean_actual_regulation_goals: float
    artifact: NHLPublicBaselineArtifact
    evidence_role: str = "REUSED_RETROSPECTIVE_DEVELOPMENT_HOLDOUT_NOT_FORWARD_BETTING_EVIDENCE"


def _utc(value: str | datetime) -> datetime:
    dt=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("validation timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _poisson_nll(y: int, lam: float) -> float:
    if y < 0 or lam <= 0:
        raise ValueError("invalid Poisson observation")
    return lam - y * log(lam) + lgamma(y + 1)


def validate_public_baseline(
    games: Iterable[NHLOfficialCompletedGame],
    *,
    fit_before: str | datetime,
    validate_start: str | datetime,
    validate_before: str | datetime,
    min_team_games: int = 10,
    ridge: float = 1.0,
    version: str = "nhl-public-boxscore-baseline-v1",
) -> NHLPublicBaselineValidation:
    fit_cut=_utc(fit_before)
    val_start=_utc(validate_start)
    val_end=_utc(validate_before)
    if not fit_cut <= val_start < val_end:
        raise ValueError("invalid NHL validation windows")
    rows=build_baseline_training_rows(games,min_team_games=min_team_games,allowed_game_types=(2,))
    train=tuple(r for r in rows if _utc(r.start_time_utc) < fit_cut)
    validation=tuple(r for r in rows if val_start <= _utc(r.start_time_utc) < val_end)
    if len(train) <= 9:
        raise ValueError("insufficient NHL baseline training rows")
    if not validation:
        raise ValueError("NHL baseline validation window is empty")
    artifact=fit_public_baseline(train,version=version,ridge=ridge)
    preds=[]; actual=[]; nll=[]
    for row in validation:
        lam=artifact.regulation_goal_rate(row.features)
        preds.append(lam)
        actual.append(float(row.regulation_goals))
        nll.append(_poisson_nll(row.regulation_goals,lam))
    errors=[p-a for p,a in zip(preds,actual)]
    return NHLPublicBaselineValidation(
        training_rows=len(train),
        validation_rows=len(validation),
        team_goal_mae=sum(abs(e) for e in errors)/len(errors),
        team_goal_rmse=sqrt(sum(e*e for e in errors)/len(errors)),
        poisson_negative_log_likelihood=sum(nll)/len(nll),
        mean_predicted_regulation_goals=sum(preds)/len(preds),
        mean_actual_regulation_goals=sum(actual)/len(actual),
        artifact=artifact,
    )


__all__=["NHLPublicBaselineValidation","validate_public_baseline"]
