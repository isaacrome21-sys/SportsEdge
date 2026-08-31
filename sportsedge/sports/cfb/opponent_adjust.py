"""Regularized opponent adjustment for CFB team-game efficiency metrics.

Raw CFB efficiency is schedule-poisoned. This module estimates offense-team and
opponent-defense effects jointly from team-game observations using ridge regression.
It is market-blind and must be fit only on rows available before the target game/fold.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping

import numpy as np


class CFBOpponentAdjustError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBOpponentAdjustError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBOpponentAdjustError(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class OpponentAdjustedMetricModel:
    metric_key: str
    teams: tuple[str, ...]
    league_intercept: float
    offense_effects: tuple[float, ...]
    defense_weakness_effects: tuple[float, ...]
    ridge_alpha: float
    training_seasons: tuple[int, ...]
    model_id: str = "CFB_SCHEDULE_ADJUSTED_RIDGE_V1"

    def _index(self, team: str) -> int:
        try:
            return self.teams.index(str(team))
        except ValueError as exc:
            raise CFBOpponentAdjustError(f"TEAM_UNSEEN:{team}") from exc

    def offense_rating(self, team: str) -> float:
        return float(self.offense_effects[self._index(team)])

    def defense_strength(self, team: str) -> float:
        return -float(self.defense_weakness_effects[self._index(team)])

    def expected_metric(self, offense_team: str, defense_team: str) -> float:
        return (
            float(self.league_intercept)
            + self.offense_rating(offense_team)
            - self.defense_strength(defense_team)
        )

    def content_hash(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def fit_schedule_adjusted_metric(
    rows: Iterable[Mapping[str, Any]],
    *,
    metric_key: str,
    test_season: int,
    ridge_alpha: float = 20.0,
    min_observations_per_team: int = 2,
) -> OpponentAdjustedMetricModel:
    """Fit y = intercept + offense_team + opponent_defense_weakness.

    Every training season must be strictly earlier than ``test_season``. This is
    stronger than merely excluding the held-out season: accidentally including a later
    season is also leakage and fails closed. Hyperparameter selection must occur in an
    inner chronological training process; this function treats ``ridge_alpha`` as an
    already-frozen input for the fold.
    """

    data = [dict(row) for row in rows]
    if len(data) < 20:
        raise CFBOpponentAdjustError("OPPONENT_ADJUST_ROWS_INSUFFICIENT")
    test = int(test_season)
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    if any(season >= test for season in seasons):
        raise CFBOpponentAdjustError("OPPONENT_ADJUST_TEST_SEASON_IN_TRAINING_OR_FUTURE")
    alpha = _num(ridge_alpha, "ridge_alpha")
    if alpha < 0.0:
        raise CFBOpponentAdjustError("OPPONENT_ADJUST_ALPHA_NEGATIVE")
    teams = tuple(sorted({str(row.get("team") or "").strip() for row in data} | {str(row.get("opponent") or "").strip() for row in data}))
    if not teams or "" in teams:
        raise CFBOpponentAdjustError("OPPONENT_ADJUST_TEAM_ID_REQUIRED")
    index = {team: i for i, team in enumerate(teams)}
    counts = {team: 0 for team in teams}
    n = len(data)
    p = 1 + 2 * len(teams)
    design = np.zeros((n, p), dtype=float)
    target = np.zeros(n, dtype=float)
    design[:, 0] = 1.0
    for i, row in enumerate(data):
        team = str(row.get("team") or "").strip()
        opponent = str(row.get("opponent") or "").strip()
        if team == opponent:
            raise CFBOpponentAdjustError("OPPONENT_ADJUST_SELF_OPPONENT")
        design[i, 1 + index[team]] = 1.0
        design[i, 1 + len(teams) + index[opponent]] = 1.0
        target[i] = _num(row.get(metric_key), metric_key)
        counts[team] += 1
        counts[opponent] += 1
    if any(count < int(min_observations_per_team) for count in counts.values()):
        missing = sorted(team for team, count in counts.items() if count < int(min_observations_per_team))
        raise CFBOpponentAdjustError("OPPONENT_ADJUST_TEAM_SAMPLE_INSUFFICIENT:" + ",".join(missing))
    penalty = np.eye(p, dtype=float) * alpha
    penalty[0, 0] = 0.0
    lhs = design.T @ design + penalty
    rhs = design.T @ target
    try:
        coef = np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        coef = np.linalg.pinv(lhs) @ rhs
    intercept = float(coef[0])
    offense = np.asarray(coef[1:1 + len(teams)], dtype=float)
    weakness = np.asarray(coef[1 + len(teams):], dtype=float)
    off_mean = float(offense.mean())
    weak_mean = float(weakness.mean())
    offense = offense - off_mean
    weakness = weakness - weak_mean
    intercept += off_mean + weak_mean
    return OpponentAdjustedMetricModel(
        metric_key=str(metric_key),
        teams=teams,
        league_intercept=intercept,
        offense_effects=tuple(map(float, offense)),
        defense_weakness_effects=tuple(map(float, weakness)),
        ridge_alpha=alpha,
        training_seasons=seasons,
    )


def build_adjusted_team_features(
    models: Mapping[str, OpponentAdjustedMetricModel],
    *,
    team: str,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for metric, model in sorted(models.items()):
        if model.metric_key != metric:
            raise CFBOpponentAdjustError("OPPONENT_ADJUST_MODEL_KEY_MISMATCH")
        out[f"adj_{metric}_offense"] = model.offense_rating(team)
        out[f"adj_{metric}_defense"] = model.defense_strength(team)
    return out
