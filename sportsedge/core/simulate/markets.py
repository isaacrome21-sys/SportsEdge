"""Derive coherent football market probabilities from one shared simulation sample."""

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


def _require_scores(
    rows: list[Mapping[str, Any]],
    home_key: str,
    away_key: str,
    error: str,
) -> tuple[list[float], list[float]]:
    if any(home_key not in row or away_key not in row for row in rows):
        raise ValueError(error)
    return ([float(row[home_key]) for row in rows], [float(row[away_key]) for row in rows])


def _moneyline(home: list[float], away: list[float]) -> dict[str, float]:
    n = float(len(home))
    margins = [h - a for h, a in zip(home, away)]
    return {
        "home_win": sum(m > 0 for m in margins) / n,
        "away_win": sum(m < 0 for m in margins) / n,
        "tie": sum(m == 0 for m in margins) / n,
    }


def _spread(home: list[float], away: list[float], line: float) -> dict[str, float]:
    result = _three_way((h - a) + float(line) for h, a in zip(home, away))
    return {
        "home_cover": result["win"],
        "away_cover": result["loss"],
        "push": result["push"],
    }


def _period_score_keys(period: str, *, include_ot: bool | None) -> tuple[str, str, str]:
    normalized = str(period).strip().lower()
    if normalized == "first_half":
        return "first_half_home_score", "first_half_away_score", "FIRST_HALF_SCORES_MISSING"
    if normalized == "second_half":
        if include_ot is None:
            raise ValueError("SECOND_HALF_OT_RULE_REQUIRED")
        if not isinstance(include_ot, bool):
            raise ValueError("SECOND_HALF_OT_RULE_MUST_BE_BOOLEAN")
        suffix = "with_ot" if include_ot else "regulation"
        return (
            f"second_half_{suffix}_home_score",
            f"second_half_{suffix}_away_score",
            "SECOND_HALF_SCORES_MISSING",
        )
    if normalized in {"q1", "q2", "q3", "q4"}:
        return f"{normalized}_home_score", f"{normalized}_away_score", "QUARTER_SCORES_MISSING"
    raise ValueError(f"UNSUPPORTED_FOOTBALL_PERIOD:{period}")


def derive_period_markets(
    simulation_rows: Iterable[Mapping[str, Any]],
    *,
    period: str,
    spread_line: float = 0.0,
    total_line: float | None = None,
    include_ot: bool | None = None,
) -> dict[str, dict[str, float]]:
    """Price one half/quarter directly from the parent simulation rows.

    No period is simulated independently. For ``second_half`` the caller must
    explicitly state whether the sportsbook settlement rule includes overtime;
    ambiguity fails closed instead of silently treating OT one way or the other.
    """

    rows = list(simulation_rows)
    if not rows:
        raise ValueError("SIMULATION_ROWS_EMPTY")
    home_key, away_key, error = _period_score_keys(period, include_ot=include_ot)
    home, away = _require_scores(rows, home_key, away_key, error)
    result: dict[str, dict[str, float]] = {
        "moneyline": _moneyline(home, away),
        "spread": _spread(home, away, spread_line),
    }
    if total_line is not None:
        result["total"] = _over_under((h + a) - float(total_line) for h, a in zip(home, away))
    return result


def derive_alternate_markets(
    simulation_rows: Iterable[Mapping[str, Any]],
    *,
    spread_lines: Iterable[float] = (),
    total_lines: Iterable[float] = (),
) -> dict[str, dict[float, dict[str, float]]]:
    """Price alternate lines as predicates over the same final-score rows."""

    rows = list(simulation_rows)
    if not rows:
        raise ValueError("SIMULATION_ROWS_EMPTY")
    home, away = _require_scores(rows, "home_score", "away_score", "FULL_GAME_SCORES_MISSING")

    spread_results: dict[float, dict[str, float]] = {}
    for raw_line in spread_lines:
        line = float(raw_line)
        if line in spread_results:
            raise ValueError(f"DUPLICATE_ALTERNATE_SPREAD:{line}")
        spread_results[line] = _spread(home, away, line)

    total_results: dict[float, dict[str, float]] = {}
    for raw_line in total_lines:
        line = float(raw_line)
        if line in total_results:
            raise ValueError(f"DUPLICATE_ALTERNATE_TOTAL:{line}")
        total_results[line] = _over_under((h + a) - line for h, a in zip(home, away))

    return {
        "alternate_spread": spread_results,
        "alternate_total": total_results,
    }


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

    The legacy first-half arguments are preserved for compatibility. New
    second-half and quarter callers should use :func:`derive_period_markets` so
    settlement-rule choices remain explicit.
    """

    rows = list(simulation_rows)
    if not rows:
        raise ValueError("SIMULATION_ROWS_EMPTY")
    home, away = _require_scores(rows, "home_score", "away_score", "FULL_GAME_SCORES_MISSING")

    markets: dict[str, dict[str, float]] = {
        "moneyline": _moneyline(home, away),
        "spread": _spread(home, away, spread_line),
    }

    if total_line is not None:
        markets["total"] = _over_under((h + a) - float(total_line) for h, a in zip(home, away))

    effective_home_tt = home_team_total_line if home_team_total_line is not None else team_total_line
    if effective_home_tt is not None:
        markets["team_total_home"] = _over_under(h - float(effective_home_tt) for h in home)
    if away_team_total_line is not None:
        markets["team_total_away"] = _over_under(a - float(away_team_total_line) for a in away)

    if first_half_total_line is not None or first_half_spread_line != 0.0:
        fh = derive_period_markets(
            rows,
            period="first_half",
            spread_line=first_half_spread_line,
            total_line=first_half_total_line,
        )
        markets["first_half_moneyline"] = fh["moneyline"]
        markets["first_half_spread"] = fh["spread"]
        if "total" in fh:
            markets["first_half_total"] = fh["total"]

    return markets
