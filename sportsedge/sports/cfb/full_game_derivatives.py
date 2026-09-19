"""Price CFB full-game derivatives from an existing joint final-score path set.

Period must be FG. First-half / quarter / player markets stay NO_ENGINE.
This module does not grant Model_P, Truth Gate, promotion, staking, or OFFICIAL.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .joint_model import CFBModelError, price_cfb_game_markets

AUTHORITY = {
    "model_p": False,
    "promotion": False,
    "staking": False,
    "official": False,
    "run_it": False,
    "truth_gate": False,
}

FULL_GAME_DERIVATIVE_MARKETS = frozenset({
    "MONEYLINE",
    "SPREAD",
    "TOTAL",
    "HOME_TEAM_TOTAL",
    "AWAY_TEAM_TOTAL",
    "ALTERNATE_SPREAD",
    "ALTERNATE_TOTAL",
})


def _num(value: object, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBModelError(f"CFB_DERIVATIVE_NOT_NUMERIC:{field}") from exc
    if out != out:
        raise CFBModelError(f"CFB_DERIVATIVE_NAN:{field}")
    return out


def _require_fg(period: object) -> None:
    if str(period or "").strip().upper() != "FG":
        raise CFBModelError("CFB_DERIVATIVE_PERIOD_NOT_FG")


def _three_way(values: list[float]) -> dict[str, float]:
    n = float(len(values))
    if n <= 0:
        raise CFBModelError("CFB_DISTRIBUTION_EMPTY")
    return {
        "over": sum(v > 0 for v in values) / n,
        "under": sum(v < 0 for v in values) / n,
        "push": sum(v == 0 for v in values) / n,
    }


def price_cfb_full_game_derivatives(
    distribution: Iterable[Mapping[str, Any]],
    *,
    period: str,
    spread_line: float,
    total_line: float,
    home_team_total_line: float | None = None,
    away_team_total_line: float | None = None,
    alternate_spreads: Iterable[float] = (),
    alternate_totals: Iterable[float] = (),
) -> dict[str, Any]:
    _require_fg(period)
    data = [dict(row) for row in distribution]
    if not data:
        raise CFBModelError("CFB_DISTRIBUTION_EMPTY")
    for row in data:
        if "home_score" not in row or "away_score" not in row:
            raise CFBModelError("CFB_SCORE_PATHS_REQUIRED")

    base = price_cfb_game_markets(data, spread_line=spread_line, total_line=total_line)
    home = [_num(row["home_score"], "home_score") for row in data]
    away = [_num(row["away_score"], "away_score") for row in data]
    margins = [h - a for h, a in zip(home, away)]
    totals = [h + a for h, a in zip(home, away)]

    out: dict[str, Any] = {
        "period": "FG",
        "moneyline": base["moneyline"],
        "spread": base["spread"],
        "total": base["total"],
        "authority": dict(AUTHORITY),
        "promotion_block_reason": "CFB_PROMOTION_EVIDENCE_REQUIRED",
        "bet_status": "BLOCKED",
    }

    if home_team_total_line is not None:
        line = _num(home_team_total_line, "home_team_total_line")
        tw = _three_way([h - line for h in home])
        out["home_team_total"] = {"line": line, **tw}
    if away_team_total_line is not None:
        line = _num(away_team_total_line, "away_team_total_line")
        tw = _three_way([a - line for a in away])
        out["away_team_total"] = {"line": line, **tw}

    alt_spreads: dict[str, Any] = {}
    seen_s: set[float] = set()
    for raw in alternate_spreads:
        line = _num(raw, "alternate_spread")
        if line in seen_s:
            raise CFBModelError(f"DUPLICATE_ALTERNATE_SPREAD:{line}")
        seen_s.add(line)
        tw = _three_way([m + line for m in margins])
        alt_spreads[str(line)] = {"home_cover": tw["over"], "away_cover": tw["under"], "push": tw["push"]}
    if alt_spreads:
        out["alternate_spread"] = alt_spreads

    alt_totals: dict[str, Any] = {}
    seen_t: set[float] = set()
    for raw in alternate_totals:
        line = _num(raw, "alternate_total")
        if line in seen_t:
            raise CFBModelError(f"DUPLICATE_ALTERNATE_TOTAL:{line}")
        seen_t.add(line)
        tw = _three_way([tot - line for tot in totals])
        alt_totals[str(line)] = tw
    if alt_totals:
        out["alternate_total"] = alt_totals
    return out
