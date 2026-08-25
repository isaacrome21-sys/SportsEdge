"""Dependency-free NFL real-history walk-forward evaluation primitives.

The score predictor is intentionally simple and diagnosable: exponentially
weighted team scoring/margin state derived only from games completed before the
game being predicted. Sportsbook fields are used only after the market-blind
score prediction exists, to define the closing spread/total event and M1 no-vig
benchmark. They never enter the M2 score-state update.

Calibration is fit strictly on prior seasons and transformed on the held-out
season. This module is an evidence producer, not a claim that the candidate
beats the market. Promotion remains fail-closed if any gate does not clear.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import erf, isfinite, log, sqrt
from typing import Any, Iterable, Mapping

from sportsedge.core.calibrate.isotonic import FoldSafeIsotonicCalibrator


@dataclass
class _TeamState:
    games: int = 0
    margin: float = 0.0
    points_for: float = 0.0
    points_against: float = 0.0

    def update(self, *, margin: float, points_for: float, points_against: float, alpha: float) -> None:
        if self.games == 0:
            self.margin = margin
            self.points_for = points_for
            self.points_against = points_against
        else:
            self.margin = alpha * margin + (1.0 - alpha) * self.margin
            self.points_for = alpha * points_for + (1.0 - alpha) * self.points_for
            self.points_against = alpha * points_against + (1.0 - alpha) * self.points_against
        self.games += 1


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def american_implied_probability(odds: Any) -> float:
    value = _float(odds)
    if value is None or value == 0:
        raise ValueError("AMERICAN_ODDS_INVALID")
    if value < 0:
        return -value / (-value + 100.0)
    return 100.0 / (value + 100.0)


def no_vig_two_way(a_odds: Any, b_odds: Any) -> tuple[float, float]:
    a = american_implied_probability(a_odds)
    b = american_implied_probability(b_odds)
    total = a + b
    if total <= 0 or not isfinite(total):
        raise ValueError("NO_VIG_TWO_WAY_INVALID")
    return a / total, b / total


def _normal_cdf(x: float, *, mean: float, sigma: float) -> float:
    if sigma <= 0 or not isfinite(sigma):
        raise ValueError("NORMAL_SIGMA_INVALID")
    z = (x - mean) / (sigma * sqrt(2.0))
    return 0.5 * (1.0 + erf(z))


def _clip_probability(value: float) -> float:
    return min(1.0 - 1e-9, max(1e-9, float(value)))


def _game_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    season = _int(row.get("season"))
    week = _int(row.get("week"))
    return (
        season if season is not None else -1,
        str(row.get("gameday") or row.get("game_date") or ""),
        week if week is not None else -1,
        str(row.get("gametime") or ""),
        str(row.get("game_id") or ""),
    )


def _team_prediction(state: _TeamState | None, *, league_points: float) -> tuple[float, float, float]:
    if state is None or state.games <= 0:
        return 0.0, league_points, league_points
    return state.margin, state.points_for, state.points_against


def _safe_novig(a: Any, b: Any) -> tuple[float | None, float | None]:
    if a in (None, "") or b in (None, ""):
        return None, None
    try:
        return no_vig_two_way(a, b)
    except ValueError:
        return None, None


def build_nfl_game_evaluations(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_history_seasons: int = 2,
    ewma_alpha: float = 0.18,
    home_field_points: float = 1.7,
    margin_sigma: float = 13.5,
    total_sigma: float = 13.0,
) -> list[dict[str, Any]]:
    """Create as-of game predictions and closing-market evaluation rows.

    nflverse ``spread_line`` is positive when the home team is favored, so a
    home cover is ``home_margin > spread_line``. Pushes are retained in the game
    ledger but excluded from binary log-loss folds.
    """
    if min_history_seasons < 0:
        raise ValueError("MIN_HISTORY_SEASONS_INVALID")
    if not 0.0 < ewma_alpha <= 1.0:
        raise ValueError("EWMA_ALPHA_INVALID")
    if margin_sigma <= 0 or total_sigma <= 0:
        raise ValueError("MODEL_SIGMA_INVALID")

    data = [dict(row) for row in rows if str(row.get("game_type", "REG")).upper() == "REG"]
    data.sort(key=_game_sort_key)
    states: dict[str, _TeamState] = {}
    completed_seasons: set[int] = set()
    current_season: int | None = None
    prior_point_sum = 0.0
    prior_team_games = 0
    out: list[dict[str, Any]] = []

    for row in data:
        season = _int(row.get("season"))
        home_score = _float(row.get("home_score"))
        away_score = _float(row.get("away_score"))
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if season is None or home_score is None or away_score is None or not home_team or not away_team:
            continue
        if home_team == away_team:
            raise ValueError("NFL_HISTORY_TEAM_COLLISION")

        if current_season is None:
            current_season = season
        elif season != current_season:
            completed_seasons.add(current_season)
            current_season = season

        league_points = prior_point_sum / prior_team_games if prior_team_games else 21.5
        home_margin_rating, home_pf, home_pa = _team_prediction(states.get(home_team), league_points=league_points)
        away_margin_rating, away_pf, away_pa = _team_prediction(states.get(away_team), league_points=league_points)

        # Market-blind score-state prediction. Closing lines/prices are not used
        # until after these two values have been fixed.
        model_margin_mu = float(home_field_points + 0.5 * (home_margin_rating - away_margin_rating))
        model_home_points = 0.5 * (home_pf + away_pa)
        model_away_points = 0.5 * (away_pf + home_pa)
        model_total_mu = float(model_home_points + model_away_points)

        if len(completed_seasons) >= min_history_seasons:
            spread_line = _float(row.get("spread_line"))
            total_line = _float(row.get("total_line"))
            home_margin = float(home_score - away_score)
            game_total = float(home_score + away_score)
            spread_push = spread_line is not None and home_margin == spread_line
            total_push = total_line is not None and game_total == total_line

            m2_home_cover = None
            home_cover_outcome = None
            if spread_line is not None:
                m2_home_cover = _clip_probability(
                    1.0 - _normal_cdf(spread_line, mean=model_margin_mu, sigma=margin_sigma)
                )
                if not spread_push:
                    home_cover_outcome = int(home_margin > spread_line)

            m2_over = None
            over_outcome = None
            if total_line is not None:
                m2_over = _clip_probability(
                    1.0 - _normal_cdf(total_line, mean=model_total_mu, sigma=total_sigma)
                )
                if not total_push:
                    over_outcome = int(game_total > total_line)

            m1_home_cover, _ = _safe_novig(row.get("home_spread_odds"), row.get("away_spread_odds"))
            m1_over, _ = _safe_novig(row.get("over_odds"), row.get("under_odds"))

            out.append({
                "game_id": str(row.get("game_id") or ""),
                "season": season,
                "week": _int(row.get("week")),
                "gameday": str(row.get("gameday") or row.get("game_date") or ""),
                "home_team": home_team,
                "away_team": away_team,
                "home_margin": home_margin,
                "game_total": game_total,
                "spread_line": spread_line,
                "total_line": total_line,
                "spread_push": bool(spread_push),
                "total_push": bool(total_push),
                "home_cover_outcome": home_cover_outcome,
                "over_outcome": over_outcome,
                "model_margin_mu": model_margin_mu,
                "model_total_mu": model_total_mu,
                "m1_home_cover_prob": m1_home_cover,
                "m2_home_cover_prob": m2_home_cover,
                "m1_over_prob": m1_over,
                "m2_over_prob": m2_over,
                "history_seasons": len(completed_seasons),
            })

        home_state = states.setdefault(home_team, _TeamState())
        away_state = states.setdefault(away_team, _TeamState())
        margin = float(home_score - away_score)
        home_state.update(
            margin=margin,
            points_for=home_score,
            points_against=away_score,
            alpha=ewma_alpha,
        )
        away_state.update(
            margin=-margin,
            points_for=away_score,
            points_against=home_score,
            alpha=ewma_alpha,
        )
        prior_point_sum += home_score + away_score
        prior_team_games += 2

    return out


def calibrate_nfl_evaluations(
    evaluations: Iterable[Mapping[str, Any]],
    *,
    min_fit_seasons: int = 2,
) -> list[dict[str, Any]]:
    """Fit isotonic calibrators on prior seasons only and transform held-out games."""
    if min_fit_seasons < 1:
        raise ValueError("MIN_CALIBRATION_FIT_SEASONS_INVALID")
    rows = [dict(row) for row in evaluations]
    seasons = sorted({int(row["season"]) for row in rows})
    for row in rows:
        row["m2_home_cover_calibrated_prob"] = None
        row["m2_over_calibrated_prob"] = None
        row["spread_calibration_fit_seasons"] = ()
        row["total_calibration_fit_seasons"] = ()

    specs = {
        "spread": ("home_cover_outcome", "m2_home_cover_prob", "m2_home_cover_calibrated_prob", "spread_calibration_fit_seasons"),
        "total": ("over_outcome", "m2_over_prob", "m2_over_calibrated_prob", "total_calibration_fit_seasons"),
    }
    for test_season in seasons:
        for _, (outcome_key, raw_key, calibrated_key, fit_key) in specs.items():
            train = [
                row for row in rows
                if int(row["season"]) < test_season
                and row.get(outcome_key) in (0, 1)
                and row.get(raw_key) is not None
            ]
            fit_seasons = tuple(sorted({int(row["season"]) for row in train}))
            if len(fit_seasons) < min_fit_seasons:
                continue
            test = [
                row for row in rows
                if int(row["season"]) == test_season
                and row.get(outcome_key) in (0, 1)
                and row.get(raw_key) is not None
            ]
            if not test:
                continue
            calibrator = FoldSafeIsotonicCalibrator().fit(
                [float(row[raw_key]) for row in train],
                [float(row[outcome_key]) for row in train],
                fit_seasons=set(fit_seasons),
                test_season=test_season,
            )
            transformed = calibrator.transform([float(row[raw_key]) for row in test])
            for row, probability in zip(test, transformed):
                row[calibrated_key] = _clip_probability(probability)
                row[fit_key] = fit_seasons
    return rows


def _log_loss(rows: list[tuple[int, float]]) -> float:
    if not rows:
        raise ValueError("EMPTY_LOG_LOSS_ROWS")
    total = 0.0
    for outcome, raw_prob in rows:
        if outcome not in (0, 1):
            raise ValueError("BINARY_OUTCOME_REQUIRED")
        p = _clip_probability(raw_prob)
        total += -(outcome * log(p) + (1 - outcome) * log(1.0 - p))
    return total / len(rows)


def build_nfl_fold_rows(
    evaluations: Iterable[Mapping[str, Any]],
    *,
    require_calibrated: bool = False,
) -> list[dict[str, Any]]:
    """Aggregate comparable M1/M2 log loss by season and market."""
    data = [dict(row) for row in evaluations]
    seasons = sorted({int(row["season"]) for row in data})
    folds: list[dict[str, Any]] = []
    specs = {
        "spread": (
            "home_cover_outcome", "m1_home_cover_prob",
            "m2_home_cover_calibrated_prob" if require_calibrated else "m2_home_cover_prob",
        ),
        "total": (
            "over_outcome", "m1_over_prob",
            "m2_over_calibrated_prob" if require_calibrated else "m2_over_prob",
        ),
    }
    for season in seasons:
        season_rows = [row for row in data if int(row["season"]) == season]
        for market, (outcome_key, m1_key, m2_key) in specs.items():
            eligible = [
                row for row in season_rows
                if row.get(outcome_key) in (0, 1) and row.get(m2_key) is not None
            ]
            if not eligible:
                continue
            comparable = [row for row in eligible if row.get(m1_key) is not None]
            if not comparable:
                continue
            m1_rows = [(int(row[outcome_key]), float(row[m1_key])) for row in comparable]
            m2_rows = [(int(row[outcome_key]), float(row[m2_key])) for row in comparable]
            m1_loss = _log_loss(m1_rows)
            m2_loss = _log_loss(m2_rows)
            folds.append({
                "season": season,
                "market": market,
                "n": len(comparable),
                "eligible_n": len(eligible),
                "m1_coverage": len(comparable) / len(eligible),
                "m1_log_loss": m1_loss,
                "m2_log_loss": m2_loss,
                "m2_beats_m1": m2_loss < m1_loss,
                "m2_probability_source": "FOLD_SAFE_ISOTONIC" if require_calibrated else "RAW_MODEL",
            })
    return folds


def build_calibration_evidence(
    evaluations: Iterable[Mapping[str, Any]],
    *,
    bins: int = 10,
    min_bin_n: int = 25,
    max_bin_deviation_threshold: float = 0.05,
) -> dict[str, dict[str, Any]]:
    """Build held-out reliability evidence from fold-safe calibrated predictions."""
    if bins <= 1:
        raise ValueError("CALIBRATION_BINS_INVALID")
    if min_bin_n <= 0:
        raise ValueError("CALIBRATION_MIN_BIN_N_INVALID")
    if not 0.0 <= max_bin_deviation_threshold <= 1.0:
        raise ValueError("CALIBRATION_THRESHOLD_INVALID")
    data = [dict(row) for row in evaluations]
    specs = {
        "spread": ("home_cover_outcome", "m2_home_cover_calibrated_prob"),
        "total": ("over_outcome", "m2_over_calibrated_prob"),
    }
    out: dict[str, dict[str, Any]] = {}
    for market, (outcome_key, probability_key) in specs.items():
        rows = [
            row for row in data
            if row.get(outcome_key) in (0, 1) and row.get(probability_key) is not None
        ]
        buckets: dict[int, list[tuple[float, int]]] = {}
        for row in rows:
            probability = _clip_probability(float(row[probability_key]))
            index = min(bins - 1, int(probability * bins))
            buckets.setdefault(index, []).append((probability, int(row[outcome_key])))

        reliability_bins: list[dict[str, Any]] = []
        deviations: list[float] = []
        for index in range(bins):
            bucket = buckets.get(index, [])
            if not bucket:
                continue
            mean_probability = sum(item[0] for item in bucket) / len(bucket)
            empirical_rate = sum(item[1] for item in bucket) / len(bucket)
            deviation = abs(empirical_rate - mean_probability)
            eligible = len(bucket) >= min_bin_n
            if eligible:
                deviations.append(deviation)
            reliability_bins.append({
                "bin": index,
                "n": len(bucket),
                "mean_probability": mean_probability,
                "empirical_rate": empirical_rate,
                "abs_deviation": deviation,
                "eligible": eligible,
            })

        max_deviation = max(deviations) if deviations else None
        passed = max_deviation is not None and max_deviation <= max_bin_deviation_threshold
        out[market] = {
            "n": len(rows),
            "bins": reliability_bins,
            "eligible_bin_count": len(deviations),
            "max_bin_deviation": max_deviation,
            "threshold": float(max_bin_deviation_threshold),
            "pass": bool(passed),
            "reason": (
                "PASS" if passed
                else "CALIBRATION_BINS_UNDERPOWERED" if max_deviation is None
                else "CALIBRATION_DEVIATION_EXCEEDS_THRESHOLD"
            ),
        }
    return out
