"""Temporal validation gate for MLB context run-adjustment candidates."""
from __future__ import annotations

from math import isfinite, sqrt
from typing import Any, Mapping

VALIDATION_VERSION = "mlb_context_temporal_validation_v1"
MIN_HOLDOUT_GAMES = 200


def _prediction_triplet(row: Mapping[str, Any]) -> tuple[float, float, float] | None:
    try:
        actual = float(row["actual_total_runs"])
        baseline = float(row["baseline_total_runs"])
        candidate = float(row["candidate_total_runs"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(isfinite(value) for value in (actual, baseline, candidate)):
        return None
    return actual, baseline, candidate


def validate_candidate(
    rows: list[Mapping[str, Any]],
    *,
    train_end: str,
    holdout_start: str,
    max_rmse_regression: float = 0.0,
) -> dict[str, Any]:
    if not train_end or not holdout_start or train_end >= holdout_start:
        raise ValueError("temporal holdout must begin after training window")

    holdout = [
        row for row in rows
        if str(row.get("game_date", "")) >= holdout_start
    ]
    parsed = [_prediction_triplet(row) for row in holdout]
    invalid_rows = sum(item is None for item in parsed)
    valid = [item for item in parsed if item is not None]

    if valid:
        baseline_rmse = sqrt(
            sum((baseline - actual) ** 2 for actual, baseline, _ in valid) / len(valid)
        )
        candidate_rmse = sqrt(
            sum((candidate - actual) ** 2 for actual, _, candidate in valid) / len(valid)
        )
    else:
        baseline_rmse = float("inf")
        candidate_rmse = float("inf")

    enough = len(valid) >= MIN_HOLDOUT_GAMES
    complete = invalid_rows == 0
    passed = (
        enough
        and complete
        and candidate_rmse <= baseline_rmse + float(max_rmse_regression)
    )
    return {
        "validation_version": VALIDATION_VERSION,
        "train_end": train_end,
        "holdout_start": holdout_start,
        "holdout_games": len(holdout),
        "valid_holdout_games": len(valid),
        "invalid_holdout_rows": invalid_rows,
        "minimum_holdout_games": MIN_HOLDOUT_GAMES,
        "baseline_rmse": baseline_rmse,
        "candidate_rmse": candidate_rmse,
        "rmse_delta": candidate_rmse - baseline_rmse,
        "status": "VALIDATED" if passed else "REJECTED",
    }
