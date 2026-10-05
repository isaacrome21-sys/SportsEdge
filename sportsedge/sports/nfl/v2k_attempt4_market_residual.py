"""NFL Attempt-4 market-anchored residual edge model.

Materially different from Attempts 1-3: the sportsbook no-vig probability is the
baseline forecast, and SportsEdge may only add a training-only team residual
overlay learned from strictly-prior completed games. No drive simulation enters
this candidate.

The state update is week-safe: every game in a (season, week) is predicted before
any result from that week is allowed to update team residual state.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Any, Mapping, Sequence

EWMA_ALPHA = 0.18
OFFSEASON_RETENTION = 0.35
RELIABILITY_PRIOR_GAMES = 8.0
SPREAD_SIGNAL_SCALE = 13.5
TOTAL_SIGNAL_SCALE = 13.0
SPREAD_RESIDUAL_CAP = 21.0
TOTAL_RESIDUAL_CAP = 28.0
BETA_GRID = (-2.0, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 2.0)
EPS = 1e-9


class Attempt4ResidualError(ValueError):
    pass


@dataclass
class TeamResidualState:
    spread_residual: float = 0.0
    total_residual: float = 0.0
    spread_games: int = 0
    total_games: int = 0

    def offseason_decay(self) -> None:
        self.spread_residual *= OFFSEASON_RETENTION
        self.total_residual *= OFFSEASON_RETENTION

    def update_spread(self, value: float) -> None:
        value = max(-SPREAD_RESIDUAL_CAP, min(SPREAD_RESIDUAL_CAP, float(value)))
        self.spread_residual = (
            value if self.spread_games == 0
            else EWMA_ALPHA * value + (1.0 - EWMA_ALPHA) * self.spread_residual
        )
        self.spread_games += 1

    def update_total(self, value: float) -> None:
        value = max(-TOTAL_RESIDUAL_CAP, min(TOTAL_RESIDUAL_CAP, float(value)))
        self.total_residual = (
            value if self.total_games == 0
            else EWMA_ALPHA * value + (1.0 - EWMA_ALPHA) * self.total_residual
        )
        self.total_games += 1


def _num(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _clip_probability(value: float) -> float:
    return min(1.0 - EPS, max(EPS, float(value)))


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


def _logit(p: float) -> float:
    p = _clip_probability(p)
    return log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def _effective(value: float, games: int) -> float:
    reliability = float(games) / (float(games) + RELIABILITY_PRIOR_GAMES)
    return float(value) * reliability


def candidate_probability(base_probability: float, signal: float, *, beta: float, scale: float) -> float:
    if scale <= 0:
        raise Attempt4ResidualError("ATTEMPT4_SIGNAL_SCALE_INVALID")
    return _clip_probability(_sigmoid(_logit(base_probability) + float(beta) * float(signal) / float(scale)))


def _sort_key(game: Mapping[str, Any]) -> tuple[int, int, str]:
    try:
        season = int(game["season"])
        week = int(game["week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Attempt4ResidualError("ATTEMPT4_GAME_SEASON_WEEK_INVALID") from exc
    return season, week, str(game.get("game_id") or "")


def build_residual_rows(schedule: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    games = [dict(row) for row in schedule.values()]
    games.sort(key=_sort_key)
    states: dict[str, TeamResidualState] = {}
    out: list[dict[str, Any]] = []
    index = 0
    prior_season: int | None = None

    while index < len(games):
        season = int(games[index]["season"])
        week = int(games[index]["week"])
        if prior_season is not None and season != prior_season:
            for state in states.values():
                state.offseason_decay()
        prior_season = season

        end = index
        while end < len(games) and int(games[end]["season"]) == season and int(games[end]["week"]) == week:
            end += 1
        week_games = games[index:end]

        pending_updates: list[tuple[str, str, float | None, float | None]] = []
        for game in week_games:
            home = str(game.get("home_team") or "").strip()
            away = str(game.get("away_team") or "").strip()
            if not home or not away or home == away:
                raise Attempt4ResidualError("ATTEMPT4_TEAM_IDENTITY_INVALID")
            market = game.get("_market")
            if not isinstance(market, Mapping):
                continue
            spread_line = _num(market.get("spread_line"))
            total_line = _num(market.get("total_line"))
            home_score = _num(game.get("home_score"))
            away_score = _num(game.get("away_score"))
            if home_score is None or away_score is None:
                continue

            hs = states.get(home, TeamResidualState())
            as_ = states.get(away, TeamResidualState())
            home_spread = _effective(hs.spread_residual, hs.spread_games)
            away_spread = _effective(as_.spread_residual, as_.spread_games)
            home_total = _effective(hs.total_residual, hs.total_games)
            away_total = _effective(as_.total_residual, as_.total_games)

            base_spread = _novig(market.get("home_spread_odds"), market.get("away_spread_odds"))
            base_total = _novig(market.get("over_odds"), market.get("under_odds"))
            margin = float(home_score - away_score)
            total = float(home_score + away_score)
            spread_push = spread_line is not None and abs(margin - spread_line) < 1e-12
            total_push = total_line is not None and abs(total - total_line) < 1e-12

            out.append({
                "game_id": str(game.get("game_id") or ""),
                "season": season,
                "week": week,
                "home_team": home,
                "away_team": away,
                "spread_line": spread_line,
                "total_line": total_line,
                "base_home_cover_probability": base_spread,
                "base_over_probability": base_total,
                "spread_signal": home_spread - away_spread,
                "total_signal": 0.5 * (home_total + away_total),
                "home_cover_outcome": None if spread_line is None or spread_push else int(margin > spread_line),
                "over_outcome": None if total_line is None or total_push else int(total > total_line),
            })

            spread_resid = None if spread_line is None else margin - spread_line
            total_resid = None if total_line is None else total - total_line
            pending_updates.append((home, away, spread_resid, total_resid))

        # No same-week outcome can affect another same-week forecast.
        for home, away, spread_resid, total_resid in pending_updates:
            hs = states.setdefault(home, TeamResidualState())
            as_ = states.setdefault(away, TeamResidualState())
            if spread_resid is not None:
                hs.update_spread(spread_resid)
                as_.update_spread(-spread_resid)
            if total_resid is not None:
                hs.update_total(total_resid)
                as_.update_total(total_resid)

        index = end
    return out


def _logloss(rows: Sequence[tuple[int, float]]) -> float:
    if not rows:
        raise Attempt4ResidualError("ATTEMPT4_EMPTY_LOGLOSS")
    total = 0.0
    for y, p in rows:
        if y not in (0, 1):
            raise Attempt4ResidualError("ATTEMPT4_BINARY_OUTCOME_REQUIRED")
        p = _clip_probability(p)
        total += -(y * log(p) + (1 - y) * log(1.0 - p))
    return total / len(rows)


def choose_beta(rows: Sequence[Mapping[str, Any]], *, market: str) -> float:
    if market == "spread":
        outcome_key, base_key, signal_key, scale = (
            "home_cover_outcome", "base_home_cover_probability", "spread_signal", SPREAD_SIGNAL_SCALE
        )
    elif market == "total":
        outcome_key, base_key, signal_key, scale = (
            "over_outcome", "base_over_probability", "total_signal", TOTAL_SIGNAL_SCALE
        )
    else:
        raise Attempt4ResidualError("ATTEMPT4_MARKET_INVALID")
    eligible = [
        row for row in rows
        if row.get(outcome_key) in (0, 1) and row.get(base_key) is not None
    ]
    if not eligible:
        raise Attempt4ResidualError("ATTEMPT4_TRAINING_ROWS_EMPTY")
    scored = []
    for beta in BETA_GRID:
        pairs = [
            (
                int(row[outcome_key]),
                candidate_probability(float(row[base_key]), float(row[signal_key]), beta=beta, scale=scale),
            )
            for row in eligible
        ]
        scored.append((_logloss(pairs), abs(float(beta)), float(beta)))
    return min(scored)[2]


def evaluate_fold(rows: Sequence[Mapping[str, Any]], *, test_season: int, market: str) -> dict[str, Any]:
    train = [row for row in rows if int(row["season"]) < int(test_season)]
    test = [row for row in rows if int(row["season"]) == int(test_season)]
    beta = choose_beta(train, market=market)
    if market == "spread":
        outcome_key, base_key, signal_key, scale = (
            "home_cover_outcome", "base_home_cover_probability", "spread_signal", SPREAD_SIGNAL_SCALE
        )
    else:
        outcome_key, base_key, signal_key, scale = (
            "over_outcome", "base_over_probability", "total_signal", TOTAL_SIGNAL_SCALE
        )
    eligible = [
        row for row in test
        if row.get(outcome_key) in (0, 1) and row.get(base_key) is not None
    ]
    if not eligible:
        raise Attempt4ResidualError(f"ATTEMPT4_TEST_ROWS_EMPTY:{test_season}:{market}")
    baseline = [(int(row[outcome_key]), float(row[base_key])) for row in eligible]
    candidate = [
        (
            int(row[outcome_key]),
            candidate_probability(float(row[base_key]), float(row[signal_key]), beta=beta, scale=scale),
        )
        for row in eligible
    ]
    return {
        "season": int(test_season),
        "market": market,
        "n": len(eligible),
        "selected_beta": beta,
        "baseline_log_loss": _logloss(baseline),
        "candidate_log_loss": _logloss(candidate),
        "candidate_beats_baseline": _logloss(candidate) < _logloss(baseline),
        "rows": [
            {"outcome": y, "probability": p}
            for y, p in candidate
        ],
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
    "BETA_GRID",
    "EWMA_ALPHA",
    "OFFSEASON_RETENTION",
    "RELIABILITY_PRIOR_GAMES",
    "Attempt4ResidualError",
    "build_residual_rows",
    "candidate_probability",
    "choose_beta",
    "evaluate_fold",
    "calibration",
]
