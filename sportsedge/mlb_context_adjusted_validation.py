"""Research-only validation helpers for the context-adjusted MLB run model.

This module has no promotion authority. It compares score distributions without
using sportsbook prices and deliberately keeps point-in-time evidence status
separate from predictive metrics.
"""
from __future__ import annotations

from math import log, sqrt
from statistics import fmean
from typing import Any, Iterable, Mapping

from .source_lineage import canonical_json_sha256
from .v7_distribution import simulate_game_distribution

VALIDATION_VERSION = "mlb_context_adjusted_validation_v1"
GAME_TOTAL_LINES = (6.5, 7.5, 8.5, 9.5)
TEAM_TOTAL_LINES = (2.5, 3.5, 4.5, 5.5)


class MLBContextAdjustedValidationError(ValueError):
    pass


def _clamp_probability(value: float) -> float:
    return min(1.0 - 1e-12, max(1e-12, float(value)))


def brier_score(rows: Iterable[tuple[float, int]]) -> float:
    material = [(float(p), int(y)) for p, y in rows]
    if not material:
        raise MLBContextAdjustedValidationError("brier requires observations")
    return float(fmean((p - y) ** 2 for p, y in material))


def log_loss(rows: Iterable[tuple[float, int]]) -> float:
    material = [(float(p), int(y)) for p, y in rows]
    if not material:
        raise MLBContextAdjustedValidationError("log_loss requires observations")
    return float(fmean(-(y * log(_clamp_probability(p)) + (1 - y) * log(_clamp_probability(1.0 - p))) for p, y in material))


def expected_calibration_error(rows: Iterable[tuple[float, int]], *, bins: int = 10) -> float:
    material = [(min(1.0, max(0.0, float(p))), int(y)) for p, y in rows]
    if not material:
        raise MLBContextAdjustedValidationError("ece requires observations")
    if bins < 2:
        raise MLBContextAdjustedValidationError("ece bins must be >= 2")
    grouped: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, y in material:
        index = min(bins - 1, int(p * bins))
        grouped[index].append((p, y))
    n = len(material)
    return float(sum((len(group) / n) * abs(fmean(p for p, _ in group) - fmean(y for _, y in group)) for group in grouped if group))


def continuous_metrics(predicted: Iterable[float], actual: Iterable[float]) -> dict[str, float]:
    pairs = [(float(p), float(y)) for p, y in zip(predicted, actual)]
    if not pairs:
        raise MLBContextAdjustedValidationError("continuous metrics require observations")
    errors = [p - y for p, y in pairs]
    return {
        "mae": float(fmean(abs(error) for error in errors)),
        "rmse": float(sqrt(fmean(error * error for error in errors))),
        "mean_error": float(fmean(errors)),
    }


def distribution_event_probabilities(*, game_id: str, away_mean_runs: float, home_mean_runs: float, model_label: str, simulations: int = 20000) -> dict[str, float]:
    if simulations < 1000:
        raise MLBContextAdjustedValidationError("simulations must be >= 1000")
    identity = canonical_json_sha256({
        "validation_version": VALIDATION_VERSION,
        "game_id": str(game_id),
        "model_label": str(model_label),
        "away_mean_runs": float(away_mean_runs),
        "home_mean_runs": float(home_mean_runs),
        "simulations": int(simulations),
    })
    distribution = simulate_game_distribution(
        away_mean_runs=float(away_mean_runs),
        home_mean_runs=float(home_mean_runs),
        total_line=0.0,
        simulations=int(simulations),
        build_hash=identity,
    )
    probabilities: dict[str, float] = {}
    for key, probability in distribution.joint_score_pmf.items():
        away_text, home_text = key.split(",", 1)
        away = int(away_text)
        home = int(home_text)
        p = float(probability)
        total = away + home
        for line in GAME_TOTAL_LINES:
            if total > line:
                event = f"GAME_TOTAL_OVER_{line:g}"
                probabilities[event] = probabilities.get(event, 0.0) + p
        for line in TEAM_TOTAL_LINES:
            if away > line:
                event = f"AWAY_TEAM_TOTAL_OVER_{line:g}"
                probabilities[event] = probabilities.get(event, 0.0) + p
            if home > line:
                event = f"HOME_TEAM_TOTAL_OVER_{line:g}"
                probabilities[event] = probabilities.get(event, 0.0) + p
    for line in GAME_TOTAL_LINES:
        probabilities.setdefault(f"GAME_TOTAL_OVER_{line:g}", 0.0)
    for line in TEAM_TOTAL_LINES:
        probabilities.setdefault(f"AWAY_TEAM_TOTAL_OVER_{line:g}", 0.0)
        probabilities.setdefault(f"HOME_TEAM_TOTAL_OVER_{line:g}", 0.0)
    return probabilities


def actual_events(*, away_runs: int, home_runs: int) -> dict[str, int]:
    total = int(away_runs) + int(home_runs)
    result: dict[str, int] = {}
    for line in GAME_TOTAL_LINES:
        result[f"GAME_TOTAL_OVER_{line:g}"] = int(total > line)
    for line in TEAM_TOTAL_LINES:
        result[f"AWAY_TEAM_TOTAL_OVER_{line:g}"] = int(int(away_runs) > line)
        result[f"HOME_TEAM_TOTAL_OVER_{line:g}"] = int(int(home_runs) > line)
    return result


def summarize_predictions(games: Iterable[Mapping[str, Any]], *, model_label: str) -> dict[str, Any]:
    material = list(games)
    if not material:
        raise MLBContextAdjustedValidationError("no validation games")
    binary_rows: list[tuple[float, int]] = []
    by_event: dict[str, list[tuple[float, int]]] = {}
    away_pred: list[float] = []
    home_pred: list[float] = []
    total_pred: list[float] = []
    away_actual: list[float] = []
    home_actual: list[float] = []
    total_actual: list[float] = []
    for game in material:
        predictions = game.get("predictions") or {}
        prediction = predictions.get(model_label) if isinstance(predictions, Mapping) else None
        if not isinstance(prediction, Mapping):
            raise MLBContextAdjustedValidationError(f"missing prediction for {model_label}")
        events = prediction.get("events")
        outcomes = game.get("actual_events")
        if not isinstance(events, Mapping) or not isinstance(outcomes, Mapping):
            raise MLBContextAdjustedValidationError("event probability/outcome map missing")
        for event, outcome in outcomes.items():
            if event not in events:
                raise MLBContextAdjustedValidationError(f"missing event probability: {event}")
            row = (float(events[event]), int(outcome))
            binary_rows.append(row)
            by_event.setdefault(str(event), []).append(row)
        a_mean = float(prediction["away_mean_runs"])
        h_mean = float(prediction["home_mean_runs"])
        a_runs = float(game["actual_away_runs"])
        h_runs = float(game["actual_home_runs"])
        away_pred.append(a_mean); home_pred.append(h_mean); total_pred.append(a_mean + h_mean)
        away_actual.append(a_runs); home_actual.append(h_runs); total_actual.append(a_runs + h_runs)
    event_metrics = {
        event: {
            "n": len(rows),
            "brier": brier_score(rows),
            "log_loss": log_loss(rows),
            "ece": expected_calibration_error(rows),
            "mean_predicted_p": float(fmean(p for p, _ in rows)),
            "observed_rate": float(fmean(y for _, y in rows)),
        }
        for event, rows in sorted(by_event.items())
    }
    return {
        "model_label": model_label,
        "games": len(material),
        "binary_event_observations": len(binary_rows),
        "binary": {
            "brier": brier_score(binary_rows),
            "log_loss": log_loss(binary_rows),
            "ece": expected_calibration_error(binary_rows),
        },
        "runs": {
            "away": continuous_metrics(away_pred, away_actual),
            "home": continuous_metrics(home_pred, home_actual),
            "total": continuous_metrics(total_pred, total_actual),
        },
        "by_event": event_metrics,
    }
