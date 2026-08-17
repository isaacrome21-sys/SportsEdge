"""Fit early-season prior weights from historical error, never assume a schedule."""
from __future__ import annotations

from typing import Iterable, Mapping, Any


def fit_weekly_prior_decay(
    rows: Iterable[Mapping[str, Any]],
    *,
    weeks: Iterable[int],
    grid_step: float = 0.05,
) -> dict[int, float]:
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
            # Prior influence is constrained to decay monotonically by week.
            if weight > previous + 1e-12:
                continue
            loss = 0.0
            for row in wr:
                target = float(row["target"])
                prior = float(row["prior_pred"])
                current = float(row["current_pred"])
                pred = weight * prior + (1.0 - weight) * current
                loss += (target - pred) ** 2
            loss /= len(wr)
            if best_loss is None or loss < best_loss - 1e-15 or (abs(loss - best_loss) <= 1e-15 and weight < best_weight):
                best_loss = loss
                best_weight = weight
        assert best_weight is not None
        result[week] = float(best_weight)
        previous = float(best_weight)
    return result
