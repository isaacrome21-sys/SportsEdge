#!/usr/bin/env python3
from __future__ import annotations

"""Walk-forward validation for the market-blind NHL public-boxscore baseline.

The coefficient artifact is frozen using games before ``--train-before``. Holdout
features may update from earlier completed holdout games, which is legitimate
walk-forward information; the target game's result is never available to its
own features. No sportsbook prices are used and this script cannot promote a
model to Model_P/Truth Gate/OFFICIAL.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean
from typing import Iterable

from sportsedge.sports.nhl.official_boxscore_source import (
    NHLOfficialCompletedGame,
    completed_game_from_json_dict,
)
from sportsedge.sports.nhl.public_baseline import (
    build_baseline_matchup,
    build_baseline_training_rows,
    fit_public_baseline,
    game_state_from_public_baseline,
)


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _load(path: Path) -> list[NHLOfficialCompletedGame]:
    games: list[NHLOfficialCompletedGame] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            game = completed_game_from_json_dict(json.loads(line))
        except Exception as exc:
            raise ValueError(f"invalid JSONL row {line_number}: {exc}") from exc
        if game.game_id in seen:
            raise ValueError(f"duplicate game id:{game.game_id}")
        seen.add(game.game_id)
        games.append(game)
    return sorted(games, key=lambda g: (_utc(g.start_time_utc), g.game_id))


def _poisson_pmf(k: int, lam: float) -> float:
    if k < 0 or lam <= 0 or not math.isfinite(lam):
        raise ValueError("valid Poisson inputs required")
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1.0))


def _winner_probability(home_rate: float, away_rate: float, *, max_goals: int = 16) -> float:
    """Independent-Poisson regulation + 50/50 OT/SO continuation."""
    home = [_poisson_pmf(k, home_rate) for k in range(max_goals + 1)]
    away = [_poisson_pmf(k, away_rate) for k in range(max_goals + 1)]
    # Tail mass above max_goals is tiny at hockey rates. Renormalize the finite
    # grid instead of silently dropping it.
    hs, ass = sum(home), sum(away)
    home = [x / hs for x in home]
    away = [x / ass for x in away]
    p_reg_win = sum(home[h] * away[a] for h in range(max_goals + 1) for a in range(max_goals + 1) if h > a)
    p_tie = sum(home[k] * away[k] for k in range(max_goals + 1))
    return min(1.0, max(0.0, p_reg_win + 0.5 * p_tie))


def _poisson_nll(y: int, lam: float) -> float:
    return lam - y * math.log(lam) + math.lgamma(y + 1.0)


def _ece(probabilities: list[float], outcomes: list[int], bins: int = 10) -> float:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("nonempty paired probabilities/outcomes required")
    total = len(probabilities)
    error = 0.0
    for b in range(bins):
        low, high = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probabilities) if low <= p < high or (b == bins - 1 and p == 1.0)]
        if not idx:
            continue
        pbar = mean(probabilities[i] for i in idx)
        ybar = mean(outcomes[i] for i in idx)
        error += len(idx) / total * abs(pbar - ybar)
    return error


def _calibration_logistic(probabilities: list[float], outcomes: list[int]) -> tuple[float, float]:
    """Return logistic calibration intercept/slope using damped Newton steps.

    Fits ``logit(P(Y=1)) = a + b*logit(p_model)``. The implementation is small,
    deterministic and dependency-free; it fails closed on singular designs.
    """
    if len(probabilities) != len(outcomes) or len(probabilities) < 20:
        raise ValueError("at least 20 paired rows required")
    x = [math.log(min(1 - 1e-9, max(1e-9, p)) / (1 - min(1 - 1e-9, max(1e-9, p)))) for p in probabilities]
    a, b = 0.0, 1.0
    for _ in range(50):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for xi, yi in zip(x, outcomes):
            eta = max(-30.0, min(30.0, a + b * xi))
            pi = 1.0 / (1.0 + math.exp(-eta))
            w = max(1e-12, pi * (1.0 - pi))
            diff = yi - pi
            g0 += diff
            g1 += diff * xi
            h00 += w
            h01 += w * xi
            h11 += w * xi * xi
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            raise ValueError("singular calibration fit")
        da = (g0 * h11 - g1 * h01) / det
        db = (g1 * h00 - g0 * h01) / det
        # Guard against separation/overshoot while retaining deterministic convergence.
        scale = min(1.0, 2.0 / max(2.0, abs(da), abs(db)))
        a += scale * da
        b += scale * db
        if max(abs(scale * da), abs(scale * db)) < 1e-9:
            break
    return a, b


def _game_winner(game: NHLOfficialCompletedGame) -> int:
    if game.home_final_goals == game.away_final_goals:
        raise ValueError(f"final NHL score cannot be tied:{game.game_id}")
    return int(game.home_final_goals > game.away_final_goals)


def main() -> int:
    parser = argparse.ArgumentParser(description="Chronological NHL public-baseline holdout validation")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--train-before", required=True, help="UTC ISO instant; coefficient fit uses games before this instant")
    parser.add_argument("--holdout-start", required=True, help="UTC ISO instant")
    parser.add_argument("--holdout-end", required=True, help="UTC ISO instant, exclusive")
    parser.add_argument("--version", default="nhl-public-boxscore-baseline-validation-v1")
    parser.add_argument("--ridge", type=float, default=1.0)
    parser.add_argument("--min-team-games", type=int, default=10)
    parser.add_argument("--game-type", action="append", type=int, dest="game_types")
    args = parser.parse_args()

    train_before = _utc(args.train_before)
    holdout_start = _utc(args.holdout_start)
    holdout_end = _utc(args.holdout_end)
    if not train_before <= holdout_start < holdout_end:
        raise ValueError("require train_before <= holdout_start < holdout_end")

    all_games = _load(args.input)
    allowed = tuple(args.game_types or (2,))
    history = [g for g in all_games if g.game_type in allowed]
    training_games = [g for g in history if _utc(g.start_time_utc) < train_before]
    holdout_games = [g for g in history if holdout_start <= _utc(g.start_time_utc) < holdout_end]
    if not training_games or not holdout_games:
        raise ValueError("training and holdout games are both required")

    rows = build_baseline_training_rows(
        training_games,
        min_team_games=args.min_team_games,
        allowed_game_types=allowed,
    )
    artifact = fit_public_baseline(rows, version=args.version, ridge=args.ridge)

    goal_errors: list[float] = []
    goal_sq_errors: list[float] = []
    goal_nll: list[float] = []
    constant_nll: list[float] = []
    total_errors: list[float] = []
    win_probabilities: list[float] = []
    outcomes: list[int] = []
    prediction_rows: list[dict[str, object]] = []

    training_team_goals = [r.regulation_goals for r in rows]
    constant_rate = mean(training_team_goals)

    for game in holdout_games:
        matchup = build_baseline_matchup(
            history,
            game_id=game.game_id,
            home_team_id=game.home_team_id,
            away_team_id=game.away_team_id,
            puck_drop=game.start_time_utc,
            min_team_games=args.min_team_games,
            allowed_game_types=allowed,
        )
        state = game_state_from_public_baseline(matchup, artifact)
        hr, ar = state.home_regulation_goals, state.away_regulation_goals
        observed = (game.home_regulation_goals, game.away_regulation_goals)
        predicted = (hr, ar)
        for y, lam in zip(observed, predicted):
            err = lam - y
            goal_errors.append(abs(err))
            goal_sq_errors.append(err * err)
            goal_nll.append(_poisson_nll(y, lam))
            constant_nll.append(_poisson_nll(y, constant_rate))
        total_errors.append(abs((hr + ar) - sum(observed)))
        p_home = _winner_probability(hr, ar)
        outcome = _game_winner(game)
        win_probabilities.append(p_home)
        outcomes.append(outcome)
        prediction_rows.append({
            "game_id": game.game_id,
            "start_time_utc": game.start_time_utc,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "pred_home_reg_goals": hr,
            "pred_away_reg_goals": ar,
            "actual_home_reg_goals": game.home_regulation_goals,
            "actual_away_reg_goals": game.away_regulation_goals,
            "pred_home_win": p_home,
            "actual_home_win": outcome,
            "latest_history_start": matchup.latest_history_start,
        })

    intercept, slope = _calibration_logistic(win_probabilities, outcomes)
    brier = mean((p - y) ** 2 for p, y in zip(win_probabilities, outcomes))
    baseline_brier = mean((0.5 - y) ** 2 for y in outcomes)
    model_nll = mean(goal_nll)
    naive_nll = mean(constant_nll)

    metrics = {
        "schema": "sportsedge.nhl.public_baseline_validation.v1",
        "authority": "DEVELOPMENT_VALIDATION / NOT Model_P / NOT TRUTH_GATE / NOT OFFICIAL",
        "train_before": train_before.isoformat(),
        "holdout_start": holdout_start.isoformat(),
        "holdout_end": holdout_end.isoformat(),
        "allowed_game_types": list(allowed),
        "training_games": len(training_games),
        "training_rows": len(rows),
        "holdout_games": len(holdout_games),
        "training_sha256": artifact.training_sha256,
        "constant_training_goal_rate": constant_rate,
        "regulation_goal_mae": mean(goal_errors),
        "regulation_goal_rmse": math.sqrt(mean(goal_sq_errors)),
        "regulation_total_mae": mean(total_errors),
        "poisson_nll_per_team_game": model_nll,
        "constant_poisson_nll_per_team_game": naive_nll,
        "poisson_nll_improvement_vs_constant": naive_nll - model_nll,
        "home_win_brier": brier,
        "home_win_brier_0p5_baseline": baseline_brier,
        "home_win_brier_improvement_vs_0p5": baseline_brier - brier,
        "home_win_ece_10bin": _ece(win_probabilities, outcomes, bins=10),
        "home_win_calibration_intercept": intercept,
        "home_win_calibration_slope": slope,
        "artifact": artifact.as_json_dict(),
        "predictions": prediction_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k not in {"artifact", "predictions"}}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
