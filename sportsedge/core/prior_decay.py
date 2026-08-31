"""Fit and freeze early-season prior weights from historical error.

The schedule is estimated on training seasons only, constrained to decay monotonically,
and serialized with a deterministic hash. Held-out and future seasons must never
participate in selection of the schedule used to score an outer fold.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class PriorDecayArtifact:
    prior_version: str
    training_seasons: tuple[int, ...]
    weeks: tuple[int, ...]
    weights: tuple[float, ...]
    loss_name: str = "MSE"
    contract: str = "CFB_PRIOR_DECAY_V1"

    def validate(self) -> "PriorDecayArtifact":
        if not self.prior_version:
            raise ValueError("PRIOR_VERSION_REQUIRED")
        if not self.training_seasons:
            raise ValueError("PRIOR_TRAINING_SEASONS_REQUIRED")
        if not self.weeks or len(self.weeks) != len(self.weights):
            raise ValueError("PRIOR_WEEK_WEIGHT_LENGTH")
        previous = 1.0
        for week, weight in zip(self.weeks, self.weights):
            if int(week) <= 0:
                raise ValueError("PRIOR_WEEK_INVALID")
            value = float(weight)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("PRIOR_WEIGHT_RANGE")
            if value > previous + 1e-12:
                raise ValueError("PRIOR_DECAY_NOT_MONOTONE")
            previous = value
        return self

    def as_schedule(self) -> dict[int, float]:
        self.validate()
        return {int(w): float(x) for w, x in zip(self.weeks, self.weights)}

    def content_hash(self) -> str:
        self.validate()
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def fit_weekly_prior_decay(
    rows: Iterable[Mapping[str, Any]],
    *,
    weeks: Iterable[int],
    grid_step: float = 0.05,
) -> dict[int, float]:
    """Backward-compatible schedule fitter.

    Callers responsible for certification should use ``fit_prior_decay_artifact`` so
    train/test season separation and versioning are machine-enforced.
    """

    if not 0.0 < grid_step <= 1.0:
        raise ValueError("GRID_STEP_OUT_OF_RANGE")
    data = list(rows)
    result: dict[int, float] = {}
    previous = 1.0
    steps = int(round(1.0 / grid_step))
    grid = [min(1.0, i * grid_step) for i in range(steps + 1)]
    if grid[-1] != 1.0:
        grid.append(1.0)

    for week in [int(w) for w in weeks]:
        wr = [r for r in data if int(r["week"]) == week]
        if not wr:
            raise ValueError(f"PRIOR_DECAY_WEEK_MISSING:{week}")
        best_weight = None
        best_loss = None
        for weight in grid:
            if weight > previous + 1e-12:
                continue
            loss = 0.0
            for row in wr:
                target = float(row["target"])
                prior = float(row["prior_pred"])
                current = float(row["current_pred"])
                if not all(isfinite(v) for v in (target, prior, current)):
                    raise ValueError("PRIOR_DECAY_NONFINITE")
                pred = weight * prior + (1.0 - weight) * current
                loss += (target - pred) ** 2
            loss /= len(wr)
            if best_loss is None or loss < best_loss - 1e-15 or (
                abs(loss - best_loss) <= 1e-15 and (best_weight is None or weight < best_weight)
            ):
                best_loss = loss
                best_weight = weight
        if best_weight is None:
            raise ValueError("PRIOR_DECAY_NO_VALID_WEIGHT")
        result[week] = float(best_weight)
        previous = float(best_weight)
    return result


def fit_prior_decay_artifact(
    rows: Iterable[Mapping[str, Any]],
    *,
    weeks: Iterable[int] = (1, 2, 3, 4),
    test_season: int,
    prior_version: str,
    grid_step: float = 0.05,
) -> PriorDecayArtifact:
    data = [dict(r) for r in rows]
    if not data:
        raise ValueError("PRIOR_DECAY_ROWS_REQUIRED")
    test = int(test_season)
    seasons = tuple(sorted({int(r["season"]) for r in data}))
    if any(season >= test for season in seasons):
        raise ValueError("PRIOR_DECAY_TEST_SEASON_IN_TRAINING_OR_FUTURE")
    requested_weeks = tuple(int(w) for w in weeks)
    schedule = fit_weekly_prior_decay(data, weeks=requested_weeks, grid_step=grid_step)
    return PriorDecayArtifact(
        prior_version=str(prior_version),
        training_seasons=seasons,
        weeks=requested_weeks,
        weights=tuple(schedule[w] for w in requested_weeks),
    ).validate()


def prior_ablation_predictions(
    rows: Iterable[Mapping[str, Any]], artifact: PriorDecayArtifact,
) -> list[dict[str, float | int]]:
    """Return with-prior and no-prior predictions for week-level ablation reports."""

    schedule = artifact.as_schedule()
    out: list[dict[str, float | int]] = []
    for row in rows:
        week = int(row["week"])
        if week not in schedule:
            continue
        prior = float(row["prior_pred"])
        current = float(row["current_pred"])
        target = float(row["target"])
        weight = schedule[week]
        out.append({
            "week": week,
            "target": target,
            "with_prior": weight * prior + (1.0 - weight) * current,
            "without_prior": current,
            "prior_weight": weight,
        })
    return out
