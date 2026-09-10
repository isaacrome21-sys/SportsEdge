"""Leakage-safe hyperparameter selection for the NFL M2 V2 candidate.

Selection is nested inside the outer training window. Candidate kernel scales
are scored only on inner held-out seasons drawn from that training window. The
outer test season and historical key-number target frequencies are never used.
Sportsbook spread/total lines are evaluation thresholds only; they are not model
features and are never passed into the score-support fit.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log
from typing import Any, Iterable, Sequence

from sportsedge.core.walkforward.season import season_walk_forward
from .m2_v2_candidate import derive_nfl_m2_v2_score_distribution, fit_nfl_m2_v2_candidate, price_nfl_m2_v2_game_markets
from .production_validation import nflverse_spread_to_home_handicap

_EPS = 1e-9
DEFAULT_NFL_M2_V2_KERNEL_GRID = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00)


@dataclass(frozen=True)
class NFLM2V2KernelSelection:
    selected_scale: float
    criterion: str
    inner_test_seasons: tuple[int, ...]
    scored_observations: int
    candidates: tuple[dict[str, Any], ...]
    fallback_used: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_scale": self.selected_scale,
            "criterion": self.criterion,
            "inner_test_seasons": list(self.inner_test_seasons),
            "scored_observations": self.scored_observations,
            "candidates": [dict(row) for row in self.candidates],
            "fallback_used": self.fallback_used,
            "outer_test_data_used": False,
            "historical_key_target_used": False,
            "market_data_used_as_model_feature": False,
        }


def _finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _clip(probability: float) -> float:
    return min(1.0 - _EPS, max(_EPS, float(probability)))


def _conditional(win: float, loss: float) -> float | None:
    denom = float(win) + float(loss)
    if not isfinite(denom) or denom <= 0.0:
        return None
    return _clip(float(win) / denom)


def _binary_log_loss(outcome: int, probability: float) -> float:
    p = _clip(probability)
    return -(int(outcome) * log(p) + (1 - int(outcome)) * log(1.0 - p))


def _score_scale_on_inner_folds(rows: list[dict[str, Any]], *, scale: float, ridge_alpha: float, min_inner_train_seasons: int) -> tuple[float | None, int, tuple[int, ...]]:
    folds = season_walk_forward(rows, season_key="season", min_train_seasons=min_inner_train_seasons)
    losses: list[float] = []
    test_seasons: list[int] = []
    for fold in folds:
        model = fit_nfl_m2_v2_candidate(fold.train_rows, ridge_alpha=ridge_alpha, kernel_scale=scale)
        if int(fold.test_season) in model.train_seasons:
            raise ValueError("NFL_M2_V2_NESTED_TEST_SEASON_IN_TRAINING")
        test_seasons.append(int(fold.test_season))
        for raw in fold.test_rows:
            row = dict(raw)
            distribution = derive_nfl_m2_v2_score_distribution(model, row)
            home_score = _finite(row.get("home_score"))
            away_score = _finite(row.get("away_score"))
            if home_score is None or away_score is None:
                continue
            actual_margin = home_score - away_score
            actual_total = home_score + away_score
            spread_line = _finite(row.get("spread_line"))
            total_line = _finite(row.get("total_line"))
            if spread_line is not None:
                home_handicap = nflverse_spread_to_home_handicap(spread_line)
                pricing = price_nfl_m2_v2_game_markets(distribution, spread_line=home_handicap, total_line=0.0)
                probability = _conditional(pricing["spread"]["home"], pricing["spread"]["away"])
                if probability is not None and actual_margin != spread_line:
                    losses.append(_binary_log_loss(int(actual_margin > spread_line), probability))
            if total_line is not None:
                pricing = price_nfl_m2_v2_game_markets(distribution, spread_line=0.0, total_line=total_line)
                probability = _conditional(pricing["total"]["over"], pricing["total"]["under"])
                if probability is not None and actual_total != total_line:
                    losses.append(_binary_log_loss(int(actual_total > total_line), probability))
    if not losses:
        return None, 0, tuple(sorted(set(test_seasons)))
    return sum(losses) / len(losses), len(losses), tuple(sorted(set(test_seasons)))


def select_nfl_m2_v2_kernel_scale(rows: Iterable[dict[str, Any]], *, candidate_scales: Sequence[float] = DEFAULT_NFL_M2_V2_KERNEL_GRID, ridge_alpha: float = 10.0, min_inner_train_seasons: int = 2, fallback_scale: float = 1.0) -> NFLM2V2KernelSelection:
    """Select kernel scale using only nested inner walk-forward observations."""
    data = [dict(row) for row in rows]
    seasons = sorted({int(row["season"]) for row in data})
    grid = tuple(float(value) for value in candidate_scales)
    if not grid or any(not isfinite(value) or value <= 0.0 for value in grid):
        raise ValueError("NFL_M2_V2_KERNEL_GRID_INVALID")
    if len(set(grid)) != len(grid):
        raise ValueError("NFL_M2_V2_KERNEL_GRID_DUPLICATE")
    fallback = float(fallback_scale)
    if not isfinite(fallback) or fallback <= 0.0:
        raise ValueError("NFL_M2_V2_KERNEL_FALLBACK_INVALID")
    if len(seasons) <= min_inner_train_seasons:
        return NFLM2V2KernelSelection(fallback, "INNER_SPREAD_TOTAL_LOG_LOSS", (), 0, (), True)
    scored: list[dict[str, Any]] = []
    all_test_seasons: set[int] = set()
    for scale in grid:
        loss, n, test_seasons = _score_scale_on_inner_folds(data, scale=scale, ridge_alpha=ridge_alpha, min_inner_train_seasons=min_inner_train_seasons)
        all_test_seasons.update(test_seasons)
        scored.append({"scale": scale, "mean_log_loss": loss, "scored_observations": n})
    eligible = [row for row in scored if row["mean_log_loss"] is not None and row["scored_observations"] > 0]
    if not eligible:
        return NFLM2V2KernelSelection(fallback, "INNER_SPREAD_TOTAL_LOG_LOSS", tuple(sorted(all_test_seasons)), 0, tuple(scored), True)
    winner = min(eligible, key=lambda row: (float(row["mean_log_loss"]), abs(float(row["scale"]) - fallback), float(row["scale"])))
    return NFLM2V2KernelSelection(float(winner["scale"]), "INNER_SPREAD_TOTAL_LOG_LOSS", tuple(sorted(all_test_seasons)), int(winner["scored_observations"]), tuple(scored), False)
