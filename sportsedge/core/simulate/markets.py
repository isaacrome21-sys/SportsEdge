"""Derive coherent football game-level market probabilities from one joint score sample."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _three_way(values: Iterable[float]) -> dict[str, float]:
    values = list(values)
    if not values:
        raise ValueError("SIMULATION_ROWS_EMPTY")
    n = float(len(values))
    return {
        "win": sum(v > 0 for v in values) / n,
        "loss": sum(v < 0 for v in values) / n,
        "push": sum(v == 0 for v in values) / n,
    }


def _over_under(values: Iterable[float]) -> dict[str, float]:
    result = _three_way(values)
    return {"over": result["win"], "under": result["loss"], "push": result["push"]}


def _require_scores(rows: list[Mapping[str, Any]], home_key: str, away_key: str, error: str) -> tuple[list[float], list[float]]:
    if any(home_key not in row or away_key not in row for row in rows):
        raise ValueError(error)
    return ([float(row[home_key]) for row in rows], [float(row[away_key]) for row in rows])


def derive_game_markets(
    simulation_rows: Iterable[Mapping[str, Any]],
    *,
    spread_line: float = 0.0,
    total_line: float | None = None,
    team_total_line: float | None = None,
    home_team_total_line: float | None = None,
    away_team_total_line: float | None = None,
    first_half_spread_line: float = 0.0,
    first_half_total_line: float | None = None,
) -> dict[str, dict[str, float]]:
    """Price supported game-level markets from the same Monte Carlo rows.

    ``spread_line`` is the home-team handicap, so a home cover occurs when
    ``home_score - away_score + spread_line > 0``. At a zero spread, home-cover
    probability therefore exactly equals home moneyline win probability.

    First-half markets are derived only when the joint sample actually carries
    first-half scores. The function fails closed rather than inventing a first-
    half split from full-game scores.
    """

    rows = list(simulation_rows)
    if not rows:
        raise ValueError("SIMULATION_ROWS_EMPTY")
    home, away = _require_scores(rows, "home_score", "away_score", "FULL_GAME_SCORES_MISSING")
    n = float(len(rows))
    margins = [h - a for h, a in zip(home, away)]

    markets: dict[str, dict[str, float]] = {
        "moneyline": {
            "home_win": sum(m > 0 for m in margins) / n,
            "away_win": sum(m < 0 for m in margins) / n,
            "tie": sum(m == 0 for m in margins) / n,
        }
    }

    spread = _three_way(m + float(spread_line) for m in margins)
    markets["spread"] = {
        "home_cover": spread["win"],
        "away_cover": spread["loss"],
        "push": spread["push"],
    }

    if total_line is not None:
        markets["total"] = _over_under((h + a) - float(total_line) for h, a in zip(home, away))

    effective_home_tt = home_team_total_line if home_team_total_line is not None else team_total_line
    if effective_home_tt is not None:
        markets["team_total_home"] = _over_under(h - float(effective_home_tt) for h in home)
    if away_team_total_line is not None:
        markets["team_total_away"] = _over_under(a - float(away_team_total_line) for a in away)

    if first_half_total_line is not None or first_half_spread_line != 0.0:
        fh_home, fh_away = _require_scores(
            rows,
            "first_half_home_score",
            "first_half_away_score",
            "FIRST_HALF_SCORES_MISSING",
        )
        fh_margins = [h - a for h, a in zip(fh_home, fh_away)]
        markets["first_half_moneyline"] = {
            "home_win": sum(m > 0 for m in fh_margins) / n,
            "away_win": sum(m < 0 for m in fh_margins) / n,
            "tie": sum(m == 0 for m in fh_margins) / n,
        }
        fh_spread = _three_way(m + float(first_half_spread_line) for m in fh_margins)
        markets["first_half_spread"] = {
            "home_cover": fh_spread["win"],
            "away_cover": fh_spread["loss"],
            "push": fh_spread["push"],
        }
        if first_half_total_line is not None:
            markets["first_half_total"] = _over_under(
                (h + a) - float(first_half_total_line) for h, a in zip(fh_home, fh_away)
            )

    return markets
