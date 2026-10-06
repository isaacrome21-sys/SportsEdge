"""Development validation for NFL_LOCATION_SYMMETRIC_RIDGE_G1.

All 2021-2025 results are explicitly reused research history. This module
compares G1 against the existing M2 ridge baseline on identical expanding
season folds. Market closing lines are reported only as external references.
"""
from __future__ import annotations

from math import isfinite, sqrt
from typing import Any, Iterable, Mapping, Sequence

from sportsedge.sports.nfl.location_symmetric_g1 import (
    CANDIDATE_FAMILY,
    DEFAULT_ALPHA_GRID,
    MODEL_ID,
    fit_nfl_location_symmetric_g1,
    select_training_only_alpha,
)
from sportsedge.sports.nfl.m2 import fit_nfl_m2_score_model

SCHEMA = "NFL_LOCATION_SYMMETRIC_G1_DEVELOPMENT_VALIDATION_V1"
OUTER_TEST_SEASONS = (2021, 2022, 2023, 2024, 2025)
REQUIRED_HISTORY_SEASONS = tuple(range(2018, 2026))
BASELINE_RIDGE_ALPHA = 10.0
FOLD_WINS_REQUIRED = 3


class NFLSymmetricLocationValidationError(ValueError):
    pass


def _actual(row: Mapping[str, Any], target: str) -> float:
    try:
        home = float(row["home_score"])
        away = float(row["away_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NFLSymmetricLocationValidationError(
            "NFL_LOCATION_G1_VALIDATION_REALIZED_SCORE_REQUIRED"
        ) from exc
    if not isfinite(home) or not isfinite(away):
        raise NFLSymmetricLocationValidationError(
            "NFL_LOCATION_G1_VALIDATION_REALIZED_SCORE_NONFINITE"
        )
    return home - away if target == "margin" else home + away


def _metrics(predictions: Sequence[float], actuals: Sequence[float]) -> dict[str, float | int]:
    if len(predictions) != len(actuals) or not predictions:
        raise NFLSymmetricLocationValidationError("NFL_LOCATION_G1_METRICS_ALIGNMENT_INVALID")
    errors = [float(pred) - float(actual) for pred, actual in zip(predictions, actuals)]
    return {
        "n": len(errors),
        "rmse": sqrt(sum(err * err for err in errors) / len(errors)),
        "mae": sum(abs(err) for err in errors) / len(errors),
    }


def _market_reference(rows: Sequence[Mapping[str, Any]], target: str) -> dict[str, Any]:
    preds: list[float] = []
    actuals: list[float] = []
    field = "spread_line" if target == "margin" else "total_line"
    for row in rows:
        raw = row.get(field)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not isfinite(value):
            continue
        # M2 market contract: spread_line is the home handicap. A home -3.5
        # closing spread therefore corresponds to a +3.5 market margin center.
        pred = -value if target == "margin" else value
        preds.append(pred)
        actuals.append(_actual(row, target))
    if not preds:
        return {
            "n": 0,
            "rmse": None,
            "mae": None,
            "source_field": field,
            "role": "REPORT_ONLY_NOT_MODEL_INPUT_NOT_PRIMARY_LOCATION_GATE",
        }
    return {
        **_metrics(preds, actuals),
        "source_field": field,
        "role": "REPORT_ONLY_NOT_MODEL_INPUT_NOT_PRIMARY_LOCATION_GATE",
    }


def _season_rows(
    rows: Sequence[Mapping[str, Any]],
    seasons: Sequence[int],
) -> list[dict[str, Any]]:
    wanted = {int(season) for season in seasons}
    return [dict(row) for row in rows if int(row["season"]) in wanted]


def validate_nfl_location_symmetric_g1(
    rows: Iterable[Mapping[str, Any]],
    *,
    alpha_grid: Sequence[float] = DEFAULT_ALPHA_GRID,
    baseline_alpha: float = BASELINE_RIDGE_ALPHA,
) -> dict[str, Any]:
    """Run the preregistered five reused-history outer folds."""
    data = [
        dict(row)
        for row in rows
        if int(row.get("season", -1)) in REQUIRED_HISTORY_SEASONS
    ]
    present = {int(row["season"]) for row in data}
    missing = set(REQUIRED_HISTORY_SEASONS) - present
    if missing:
        raise NFLSymmetricLocationValidationError(
            "NFL_LOCATION_G1_REQUIRED_HISTORY_SEASONS_MISSING:"
            + ",".join(str(season) for season in sorted(missing))
        )

    fold_reports: list[dict[str, Any]] = []
    aggregate: dict[str, dict[str, list[float]]] = {
        target: {
            "candidate": [],
            "baseline": [],
            "actual": [],
        }
        for target in ("margin", "total")
    }

    for test_season in OUTER_TEST_SEASONS:
        train_seasons = tuple(range(2018, int(test_season)))
        train_rows = _season_rows(data, train_seasons)
        test_rows = _season_rows(data, (test_season,))
        if not train_rows or not test_rows:
            raise NFLSymmetricLocationValidationError(
                f"NFL_LOCATION_G1_OUTER_FOLD_EMPTY:{test_season}"
            )
        if any(int(row["season"]) >= test_season for row in train_rows):
            raise AssertionError("NFL_LOCATION_G1_OUTER_TRAIN_LEAKAGE")

        margin_selection = select_training_only_alpha(
            train_rows,
            target="margin",
            alpha_grid=alpha_grid,
            min_train_seasons=2,
        )
        total_selection = select_training_only_alpha(
            train_rows,
            target="total",
            alpha_grid=alpha_grid,
            min_train_seasons=2,
        )
        candidate = fit_nfl_location_symmetric_g1(
            train_rows,
            margin_alpha=float(margin_selection["selected_alpha"]),
            total_alpha=float(total_selection["selected_alpha"]),
        )
        baseline = fit_nfl_m2_score_model(
            train_rows,
            ridge_alpha=float(baseline_alpha),
        )
        if test_season in candidate.train_seasons or test_season in baseline.train_seasons:
            raise AssertionError("NFL_LOCATION_G1_OUTER_TEST_IN_TRAINING")

        candidate_margin: list[float] = []
        candidate_total: list[float] = []
        baseline_margin: list[float] = []
        baseline_total: list[float] = []
        actual_margin: list[float] = []
        actual_total: list[float] = []
        for row in test_rows:
            cand_margin, cand_total = candidate.predict(row)
            base_margin, base_total = baseline.predict(row)
            candidate_margin.append(cand_margin)
            candidate_total.append(cand_total)
            baseline_margin.append(base_margin)
            baseline_total.append(base_total)
            actual_margin.append(_actual(row, "margin"))
            actual_total.append(_actual(row, "total"))

        margin_candidate_metrics = _metrics(candidate_margin, actual_margin)
        margin_baseline_metrics = _metrics(baseline_margin, actual_margin)
        total_candidate_metrics = _metrics(candidate_total, actual_total)
        total_baseline_metrics = _metrics(baseline_total, actual_total)

        fold_reports.append({
            "test_season": test_season,
            "train_seasons": list(train_seasons),
            "n": len(test_rows),
            "alpha_selection": {
                "margin": margin_selection,
                "total": total_selection,
            },
            "margin": {
                "candidate": margin_candidate_metrics,
                "m2_baseline": margin_baseline_metrics,
                "candidate_beats_m2_rmse": (
                    float(margin_candidate_metrics["rmse"])
                    < float(margin_baseline_metrics["rmse"])
                ),
                "candidate_beats_m2_mae": (
                    float(margin_candidate_metrics["mae"])
                    < float(margin_baseline_metrics["mae"])
                ),
                "closing_market_reference": _market_reference(test_rows, "margin"),
            },
            "total": {
                "candidate": total_candidate_metrics,
                "m2_baseline": total_baseline_metrics,
                "candidate_beats_m2_rmse": (
                    float(total_candidate_metrics["rmse"])
                    < float(total_baseline_metrics["rmse"])
                ),
                "candidate_beats_m2_mae": (
                    float(total_candidate_metrics["mae"])
                    < float(total_baseline_metrics["mae"])
                ),
                "closing_market_reference": _market_reference(test_rows, "total"),
            },
        })

        aggregate["margin"]["candidate"].extend(candidate_margin)
        aggregate["margin"]["baseline"].extend(baseline_margin)
        aggregate["margin"]["actual"].extend(actual_margin)
        aggregate["total"]["candidate"].extend(candidate_total)
        aggregate["total"]["baseline"].extend(baseline_total)
        aggregate["total"]["actual"].extend(actual_total)

    target_summary: dict[str, Any] = {}
    for target in ("margin", "total"):
        candidate_metrics = _metrics(
            aggregate[target]["candidate"],
            aggregate[target]["actual"],
        )
        baseline_metrics = _metrics(
            aggregate[target]["baseline"],
            aggregate[target]["actual"],
        )
        rmse_fold_wins = sum(
            bool(fold[target]["candidate_beats_m2_rmse"])
            for fold in fold_reports
        )
        mae_fold_wins = sum(
            bool(fold[target]["candidate_beats_m2_mae"])
            for fold in fold_reports
        )
        passed = (
            rmse_fold_wins >= FOLD_WINS_REQUIRED
            and mae_fold_wins >= FOLD_WINS_REQUIRED
            and float(candidate_metrics["rmse"]) < float(baseline_metrics["rmse"])
            and float(candidate_metrics["mae"]) < float(baseline_metrics["mae"])
        )
        target_summary[target] = {
            "candidate": candidate_metrics,
            "m2_baseline": baseline_metrics,
            "rmse_fold_wins": rmse_fold_wins,
            "mae_fold_wins": mae_fold_wins,
            "fold_total": len(OUTER_TEST_SEASONS),
            "required_fold_wins": FOLD_WINS_REQUIRED,
            "aggregate_rmse_strictly_lower": (
                float(candidate_metrics["rmse"]) < float(baseline_metrics["rmse"])
            ),
            "aggregate_mae_strictly_lower": (
                float(candidate_metrics["mae"]) < float(baseline_metrics["mae"])
            ),
            "passed": passed,
        }

    overall_pass = bool(
        target_summary["margin"]["passed"]
        and target_summary["total"]["passed"]
    )
    return {
        "schema": SCHEMA,
        "candidate_family": CANDIDATE_FAMILY,
        "model_id": MODEL_ID,
        "status": (
            "DEVELOPMENT_LOCATION_PASS"
            if overall_pass
            else "DEVELOPMENT_LOCATION_FAIL"
        ),
        "evidence_role": "REUSED_RESEARCH_HISTORY_NOT_UNTOUCHED_PROMOTION_EVIDENCE",
        "outer_test_seasons": list(OUTER_TEST_SEASONS),
        "baseline_model_id": "nfl_m2_ridge_v1",
        "baseline_ridge_alpha": float(baseline_alpha),
        "market_fields_used_as_model_inputs": false,
        "folds": fold_reports,
        "summary": target_summary,
        "location_gate_pass": overall_pass,
        "discrete_v2_distribution_gate_eligible": overall_pass,
        "authority": {
            "research_only": true,
            "model_p": false,
            "promotion": false,
            "staking": false,
            "official": false,
        },
    }


__all__ = [
    "BASELINE_RIDGE_ALPHA",
    "FOLD_WINS_REQUIRED",
    "OUTER_TEST_SEASONS",
    "REQUIRED_HISTORY_SEASONS",
    "SCHEMA",
    "NFLSymmetricLocationValidationError",
    "validate_nfl_location_symmetric_g1",
]
