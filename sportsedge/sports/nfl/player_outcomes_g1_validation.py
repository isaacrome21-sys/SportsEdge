"""Chronological validation for NFL player outcome engine G1.

Research-only. No market prices are consumed and no runtime authority is granted.
"""
from __future__ import annotations

from math import isfinite, log, sqrt
from statistics import mean
from typing import Any, Iterable

from .player_outcomes_g1 import fit_count_distribution

_EPS = 1e-9


def _clip(p: float) -> float:
    return min(1.0 - _EPS, max(_EPS, float(p)))


def probability_metrics(pairs: Iterable[tuple[int, float]]) -> dict[str, float]:
    rows = []
    for y, p in pairs:
        if y not in (0, 1) or not isfinite(float(p)) or not 0 <= float(p) <= 1:
            raise ValueError("NFL_PROP_G1_INVALID_PROBABILITY_EVAL")
        rows.append((int(y), _clip(float(p))))
    if not rows:
        raise ValueError("NFL_PROP_G1_EMPTY_PROBABILITY_EVAL")
    brier = mean((p - y) ** 2 for y, p in rows)
    log_loss = mean(-(y * log(p) + (1 - y) * log(1 - p)) for y, p in rows)
    return {"n": len(rows), "brier": brier, "log_loss": log_loss}


def quantity_metrics(actual_pred: Iterable[tuple[float, float]]) -> dict[str, float]:
    rows = [(float(a), float(p)) for a, p in actual_pred]
    if not rows:
        raise ValueError("NFL_PROP_G1_EMPTY_QUANTITY_EVAL")
    if any(not isfinite(a) or not isfinite(p) for a, p in rows):
        raise ValueError("NFL_PROP_G1_INVALID_QUANTITY_EVAL")
    errors = [p - a for a, p in rows]
    return {
        "n": len(rows),
        "mae": mean(abs(e) for e in errors),
        "rmse": sqrt(mean(e * e for e in errors)),
    }


def chronological_receptions_readout(
    rows: Iterable[dict[str, Any]],
    *,
    line: float = 4.5,
    min_prior_games: int = 5,
) -> dict[str, Any]:
    """Walk forward one player at a time using only prior games.

    Rows must include player_id, season, week, receptions. Each prediction uses
    only rows with an earlier (season, week) for the same player.
    """
    if isinstance(min_prior_games, bool) or not isinstance(min_prior_games, int) or min_prior_games < 1:
        raise ValueError("NFL_PROP_G1_INVALID_MIN_PRIOR_GAMES")
    line = float(line)
    if not isfinite(line) or line < 0:
        raise ValueError("NFL_PROP_G1_INVALID_LINE")
    # Validate the complete input before fitting anything. One player-week is
    # one observation; duplicates cannot become prior history for each other.
    data = []
    seen = set()
    for source in rows:
        row = dict(source)
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            raise ValueError("NFL_PROP_G1_PLAYER_ID_REQUIRED")
        row["player_id"] = player_id
        for key in ("season", "week"):
            value = row.get(key)
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError("NFL_PROP_G1_INVALID_CHRONOLOGY") from None
            if isinstance(value, bool) or not isfinite(number) or not number.is_integer() or number <= 0:
                raise ValueError("NFL_PROP_G1_INVALID_CHRONOLOGY")
            row[key] = int(number)
        identity = (player_id, row["season"], row["week"])
        if identity in seen:
            raise ValueError("NFL_PROP_G1_DUPLICATE_PLAYER_WEEK")
        seen.add(identity)
        value = row.get("receptions")
        try:
            current = float(value)
        except (TypeError, ValueError):
            raise ValueError("NFL_PROP_G1_INVALID_RECEPTIONS") from None
        if isinstance(value, bool) or not isfinite(current) or current < 0 or not current.is_integer():
            raise ValueError("NFL_PROP_G1_INVALID_RECEPTIONS")
        row["receptions"] = current
        data.append(row)
    data.sort(key=lambda r: (int(r["season"]), int(r["week"]), str(r.get("player_id") or "")))
    history: dict[str, list[dict[str, Any]]] = {}
    probability_rows: list[tuple[int, float]] = []
    quantity_rows: list[tuple[float, float]] = []
    predictions: list[dict[str, Any]] = []

    for row in data:
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            raise ValueError("NFL_PROP_G1_PLAYER_ID_REQUIRED")
        prior = history.setdefault(player_id, [])
        current = row["receptions"]
        if len(prior) >= min_prior_games:
            values = [r["receptions"] for r in prior]
            dist = fit_count_distribution(values)
            p_over = dist.prob_over_count_line(line)
            outcome = int(current > line)
            probability_rows.append((outcome, p_over))
            quantity_rows.append((current, dist.mean))
            predictions.append({
                "player_id": player_id,
                "season": int(row["season"]),
                "week": int(row["week"]),
                "line": float(line),
                "actual_receptions": current,
                "predicted_mean": dist.mean,
                "prob_over": p_over,
                "distribution_family": dist.family,
                "prior_game_count": len(prior),
            })
        prior.append(row)

    return {
        "schema": "SPORTSEDGE_NFL_PLAYER_OUTCOME_G1_RECEPTIONS_READOUT_V1",
        "status": "RESEARCH_ONLY",
        "market_prices_consumed": False,
        "random_split_used": False,
        "probability_metrics": probability_metrics(probability_rows),
        "quantity_metrics": quantity_metrics(quantity_rows),
        "predictions": predictions,
    }
