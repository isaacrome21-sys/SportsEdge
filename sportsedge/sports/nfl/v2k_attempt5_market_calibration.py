"""NFL V2K Attempt-5 market calibration candidate.

Final governed development candidate.  Unlike Attempts 1-3 (drive simulation)
and Attempt 4 (recursive team residual state), this model starts from the paired
two-way no-vig market probability and applies only a training-selected,
low-dimensional calibration overlay using the posted line level.

No team outcomes, roster data, drive data, or same-week result state enter a
prediction.  Sportsbook fields are the explicit predictive baseline for this
market-anchored candidate.
"""
from __future__ import annotations

from math import exp, isfinite, log
from typing import Any, Mapping, Sequence

INTERCEPT_GRID = (-0.12, -0.08, -0.04, 0.0, 0.04, 0.08, 0.12)
LINE_BETA_GRID = (-0.24, -0.16, -0.08, 0.0, 0.08, 0.16, 0.24)
SPREAD_LINE_SCALE = 7.0
TOTAL_LINE_CENTER = 44.0
TOTAL_LINE_SCALE = 10.0
FAIR_SPREAD_SCALE = 13.5
FAIR_TOTAL_SCALE = 13.0
EPS = 1e-9


class Attempt5CalibrationError(ValueError):
    pass


def _num(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _american_probability(value: Any) -> float | None:
    odds = _num(value)
    if odds is None or odds == 0:
        return None
    return (-odds / (-odds + 100.0)) if odds < 0 else (100.0 / (odds + 100.0))


def _novig(a: Any, b: Any) -> float | None:
    pa = _american_probability(a)
    pb = _american_probability(b)
    if pa is None or pb is None or pa + pb <= 0:
        return None
    return pa / (pa + pb)


def _clip_probability(p: float) -> float:
    return min(1.0 - EPS, max(EPS, float(p)))


def _logit(p: float) -> float:
    p = _clip_probability(p)
    return log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def line_feature(market: str, line: float) -> float:
    if market == "spread":
        raw = float(line) / SPREAD_LINE_SCALE
    elif market == "total":
        raw = (float(line) - TOTAL_LINE_CENTER) / TOTAL_LINE_SCALE
    else:
        raise Attempt5CalibrationError("ATTEMPT5_MARKET_INVALID")
    return max(-2.0, min(2.0, raw))


def candidate_probability(
    base_probability: float,
    line_value: float,
    *,
    market: str,
    intercept: float,
    line_beta: float,
) -> float:
    x = _logit(base_probability)
    x += float(intercept) + float(line_beta) * line_feature(market, line_value)
    return _clip_probability(_sigmoid(x))


def fair_market_center(*, line: float, probability: float, market: str) -> float:
    if market == "spread":
        scale = FAIR_SPREAD_SCALE
    elif market == "total":
        scale = FAIR_TOTAL_SCALE
    else:
        raise Attempt5CalibrationError("ATTEMPT5_MARKET_INVALID")
    return float(line) + scale * _logit(probability)


def build_calibration_rows(schedule: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for game in schedule.values():
        try:
            season = int(game["season"])
            week = int(game["week"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Attempt5CalibrationError("ATTEMPT5_GAME_SEASON_WEEK_INVALID") from exc
        market = game.get("_market")
        if not isinstance(market, Mapping):
            continue
        home_score = _num(game.get("home_score"))
        away_score = _num(game.get("away_score"))
        spread_line = _num(market.get("spread_line"))
        total_line = _num(market.get("total_line"))
        if home_score is None or away_score is None:
            continue
        margin = home_score - away_score
        total = home_score + away_score
        base_spread = _novig(market.get("home_spread_odds"), market.get("away_spread_odds"))
        base_total = _novig(market.get("over_odds"), market.get("under_odds"))
        spread_push = spread_line is not None and abs(margin - spread_line) < 1e-12
        total_push = total_line is not None and abs(total - total_line) < 1e-12
        out.append({
            "game_id": str(game.get("game_id") or ""),
            "season": season,
            "week": week,
            "spread_line": spread_line,
            "total_line": total_line,
            "base_home_cover_probability": base_spread,
            "base_over_probability": base_total,
            "home_cover_outcome": None if spread_line is None or spread_push else int(margin > spread_line),
            "over_outcome": None if total_line is None or total_push else int(total > total_line),
        })
    return sorted(out, key=lambda r: (r["season"], r["week"], r["game_id"]))


def _logloss(rows: Sequence[tuple[int, float]]) -> float:
    if not rows:
        raise Attempt5CalibrationError("ATTEMPT5_EMPTY_LOGLOSS")
    total = 0.0
    for y, p in rows:
        if y not in (0, 1):
            raise Attempt5CalibrationError("ATTEMPT5_BINARY_OUTCOME_REQUIRED")
        p = _clip_probability(p)
        total += -(y * log(p) + (1 - y) * log(1.0 - p))
    return total / len(rows)


def _keys(market: str):
    if market == "spread":
        return "home_cover_outcome", "base_home_cover_probability", "spread_line"
    if market == "total":
        return "over_outcome", "base_over_probability", "total_line"
    raise Attempt5CalibrationError("ATTEMPT5_MARKET_INVALID")


def choose_parameters(rows: Sequence[Mapping[str, Any]], *, market: str) -> tuple[float, float]:
    outcome_key, base_key, line_key = _keys(market)
    eligible = [
        r for r in rows
        if r.get(outcome_key) in (0, 1) and r.get(base_key) is not None and r.get(line_key) is not None
    ]
    if not eligible:
        raise Attempt5CalibrationError("ATTEMPT5_TRAINING_ROWS_EMPTY")
    scored = []
    for intercept in INTERCEPT_GRID:
        for line_beta in LINE_BETA_GRID:
            pairs = [
                (
                    int(r[outcome_key]),
                    candidate_probability(
                        float(r[base_key]), float(r[line_key]), market=market,
                        intercept=intercept, line_beta=line_beta,
                    ),
                )
                for r in eligible
            ]
            loss = _logloss(pairs)
            complexity = abs(intercept) + abs(line_beta)
            scored.append((loss, complexity, abs(intercept), abs(line_beta), intercept, line_beta))
    best = min(scored)
    return float(best[-2]), float(best[-1])


def evaluate_fold(rows: Sequence[Mapping[str, Any]], *, test_season: int, market: str) -> dict[str, Any]:
    train = [r for r in rows if int(r["season"]) < int(test_season)]
    test = [r for r in rows if int(r["season"]) == int(test_season)]
    intercept, line_beta = choose_parameters(train, market=market)
    outcome_key, base_key, line_key = _keys(market)
    eligible = [
        r for r in test
        if r.get(outcome_key) in (0, 1) and r.get(base_key) is not None and r.get(line_key) is not None
    ]
    if not eligible:
        raise Attempt5CalibrationError(f"ATTEMPT5_TEST_ROWS_EMPTY:{test_season}:{market}")
    baseline = [(int(r[outcome_key]), float(r[base_key])) for r in eligible]
    candidate = [
        (
            int(r[outcome_key]),
            candidate_probability(
                float(r[base_key]), float(r[line_key]), market=market,
                intercept=intercept, line_beta=line_beta,
            ),
        )
        for r in eligible
    ]
    bll = _logloss(baseline)
    cll = _logloss(candidate)
    return {
        "season": int(test_season),
        "market": market,
        "n": len(eligible),
        "selected_intercept": intercept,
        "selected_line_beta": line_beta,
        "baseline_log_loss": bll,
        "candidate_log_loss": cll,
        "candidate_beats_baseline": cll < bll,
        "rows": [{"outcome": y, "probability": p} for y, p in candidate],
    }


def calibration(rows: Sequence[Mapping[str, Any]], *, bins: int = 10, min_bin_n: int = 25) -> dict[str, Any]:
    bucketed: dict[int, list[tuple[float, int]]] = {}
    for row in rows:
        p = _clip_probability(float(row["probability"]))
        y = int(row["outcome"])
        bucketed.setdefault(min(bins - 1, int(p * bins)), []).append((p, y))
    details = []
    eligible_deviation = []
    for idx in range(bins):
        bucket = bucketed.get(idx, [])
        if not bucket:
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        rate = sum(y for _, y in bucket) / len(bucket)
        dev = abs(mean_p - rate)
        eligible = len(bucket) >= min_bin_n
        if eligible:
            eligible_deviation.append(dev)
        details.append({
            "bin": idx, "n": len(bucket), "mean_probability": mean_p,
            "empirical_rate": rate, "abs_deviation": dev, "eligible": eligible,
        })
    return {
        "n": sum(len(v) for v in bucketed.values()),
        "bins": details,
        "max_bin_deviation": max(eligible_deviation) if eligible_deviation else None,
    }


__all__ = [
    "INTERCEPT_GRID", "LINE_BETA_GRID", "FAIR_SPREAD_SCALE", "FAIR_TOTAL_SCALE",
    "Attempt5CalibrationError", "build_calibration_rows", "candidate_probability",
    "fair_market_center", "choose_parameters", "evaluate_fold", "calibration",
]
