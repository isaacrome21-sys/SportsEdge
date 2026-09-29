#!/usr/bin/env python3
"""Strict-prior diagnostic audit of the current MLB shared game engine.

This is a diagnostic, not promotion evidence. It compares current SportsEdge
pregame game-distribution forecasts with final regular-season scores from games
strictly before the requested cutoff. No sportsbook prices are used, so this
cannot establish market edge, CLV, ROI, or Truth-Gate qualification.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from math import sqrt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import (
    DEFAULT_EXTRA_HALF_INNING_MEAN,
    DEFAULT_FIRST_INNING_DISPERSION_R,
    DEFAULT_FIRST_INNING_SHARE,
    V7_DISTRIBUTION_VERSION,
    simulate_game_distribution,
)


def _get_json(url: str):
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _schedule(start: date, end: date) -> list[dict]:
    q = urlencode({
        "sportId": 1,
        "gameType": "R",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "hydrate": "linescore,team",
    })
    payload = _get_json(f"https://statsapi.mlb.com/api/v1/schedule?{q}")
    out = []
    for day in payload.get("dates") or []:
        for game in day.get("games") or []:
            status = (game.get("status") or {}).get("abstractGameState")
            if str(status).lower() != "final":
                continue
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            if away.get("score") is None or home.get("score") is None:
                continue
            out.append({
                "game_pk": int(game["gamePk"]),
                "official_date": str(game.get("officialDate")),
                "away_team_id": int(away_team["id"]),
                "home_team_id": int(home_team["id"]),
                "away_team": str(away_team.get("name") or away_team["id"]),
                "home_team": str(home_team.get("name") or home_team["id"]),
                "away_score": int(away["score"]),
                "home_score": int(home["score"]),
            })
    out.sort(key=lambda g: (g["official_date"], g["game_pk"]))
    return out


def _pmf_rows(pmf: dict[str, float]):
    for key, p in pmf.items():
        away, home = key.split(",", 1)
        yield int(away), int(home), float(p)


def _line_prob(pmf: dict[str, float], line: float) -> tuple[float, float, float]:
    over = under = push = 0.0
    for away, home, p in _pmf_rows(pmf):
        total = away + home
        if total > line:
            over += p
        elif total < line:
            under += p
        else:
            push += p
    return over, under, push


def _calibration_bins(rows: list[tuple[float, int]], width: float = 0.10) -> list[dict]:
    bins = []
    lo = 0.0
    while lo < 1.0 - 1e-12:
        hi = min(1.0, lo + width)
        bucket = [(p, y) for p, y in rows if (lo <= p < hi) or (hi == 1.0 and lo <= p <= hi)]
        if bucket:
            bins.append({
                "lo": round(lo, 2),
                "hi": round(hi, 2),
                "n": len(bucket),
                "mean_p": sum(p for p, _ in bucket) / len(bucket),
                "observed_rate": sum(y for _, y in bucket) / len(bucket),
            })
        lo = hi
    return bins


def _binary_summary(rows: list[tuple[float, int]]) -> dict:
    if not rows:
        return {"n": 0}
    n = len(rows)
    mean_p = sum(p for p, _ in rows) / n
    observed = sum(y for _, y in rows) / n
    brier = sum((p - y) ** 2 for p, y in rows) / n
    return {
        "n": n,
        "mean_predicted_probability": mean_p,
        "observed_rate": observed,
        "calibration_gap_pp": 100.0 * (mean_p - observed),
        "brier": brier,
        "bins": _calibration_bins(rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default="2026-09-27")
    ap.add_argument("--max-games", type=int, default=250)
    ap.add_argument("--simulations", type=int, default=100000)
    ap.add_argument("--output", default="artifacts/mlb_game_engine_recent_audit.json")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end >= date(2026, 9, 29):
        raise SystemExit("audit end must be strictly before 2026-09-29")
    if args.simulations < 100000:
        raise SystemExit("audit uses the production 100k simulation floor")

    games = _schedule(start, end)
    if args.max_games > 0 and len(games) > args.max_games:
        games = games[-args.max_games:]

    source = MLBGenericHistorySource(retrieved_at=datetime(2026, 9, 29, tzinfo=timezone.utc))
    thresholds = [6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5]
    line_rows: dict[float, list[tuple[float, int]]] = {line: [] for line in thresholds}
    home_ml_rows: list[tuple[float, int]] = []
    game_rows = []
    failures = []

    for i, game in enumerate(games, 1):
        try:
            target_date = date.fromisoformat(game["official_date"])
            feature = source.feature_row(
                game_pk=game["game_pk"],
                market="TOTALS",
                entity_id=str(game["game_pk"]),
                target_date=target_date,
                away_team_id=game["away_team_id"],
                home_team_id=game["home_team_id"],
            )
            away_mean = float(feature["away_mean_runs"])
            home_mean = float(feature["home_mean_runs"])
            feature_hash = feature.get("source_subset_hash")
            build_hash = canonical_json_sha256({
                "engine": V7_DISTRIBUTION_VERSION,
                "game_id": str(game["game_pk"]),
                "away_mean_runs": away_mean,
                "home_mean_runs": home_mean,
                "feature_source_hash": feature_hash,
            })
            dist = simulate_game_distribution(
                away_mean_runs=away_mean,
                home_mean_runs=home_mean,
                total_line=0.0,
                simulations=args.simulations,
                build_hash=build_hash,
                first_inning_share=DEFAULT_FIRST_INNING_SHARE,
                first_inning_dispersion_r=DEFAULT_FIRST_INNING_DISPERSION_R,
                extra_half_inning_mean=DEFAULT_EXTRA_HALF_INNING_MEAN,
            )
            expected_total = sum((away + home) * p for away, home, p in _pmf_rows(dist.joint_score_pmf))
            actual_total = game["away_score"] + game["home_score"]
            p_home = sum(p for away, home, p in _pmf_rows(dist.joint_score_pmf) if home > away)
            home_ml_rows.append((p_home, 1 if game["home_score"] > game["away_score"] else 0))

            line_probs = {}
            for line in thresholds:
                p_over, p_under, p_push = _line_prob(dist.joint_score_pmf, line)
                settled = p_over / (p_over + p_under) if p_over + p_under > 0 else None
                line_probs[str(line)] = {
                    "p_over": p_over,
                    "p_under": p_under,
                    "p_push": p_push,
                    "p_over_ex_push": settled,
                }
                if actual_total == line:
                    continue
                if settled is not None:
                    line_rows[line].append((settled, 1 if actual_total > line else 0))

            game_rows.append({
                **game,
                "strict_prior_away_mean_runs": away_mean,
                "strict_prior_home_mean_runs": home_mean,
                "model_input_total_mean": away_mean + home_mean,
                "simulated_expected_final_total": expected_total,
                "actual_final_total": actual_total,
                "total_error_model_minus_actual": expected_total - actual_total,
                "model_home_win_probability": p_home,
                "line_probabilities": line_probs,
                "feature_source_hash": feature_hash,
                "distribution_sha256": dist.result_sha256,
            })
            print(f"[{i}/{len(games)}] {game['game_pk']} {game['away_team']} @ {game['home_team']} ok")
        except Exception as exc:
            failures.append({"game": game, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{i}/{len(games)}] {game['game_pk']} FAILED {type(exc).__name__}: {exc}")

    n = len(game_rows)
    if not n:
        raise SystemExit("no games audited")
    errors = [row["total_error_model_minus_actual"] for row in game_rows]
    abs_errors = [abs(x) for x in errors]
    sq_errors = [x * x for x in errors]
    predicted = [row["simulated_expected_final_total"] for row in game_rows]
    actual = [row["actual_final_total"] for row in game_rows]

    payload = {
        "schema_version": 1,
        "audit": "MLB_GAME_ENGINE_STRICT_PRIOR_RECENT_V1",
        "engine_version": V7_DISTRIBUTION_VERSION,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "requested_max_games": args.max_games,
        "simulations_per_game": args.simulations,
        "games_requested": len(games),
        "games_audited": n,
        "failures": failures,
        "methodology": [
            "Regular-season final games only; audit cutoff is strictly before 2026-09-29.",
            "For each target game, MLBGenericHistorySource uses only game-log rows dated before that target date.",
            "The current V7 shared score distribution is simulated at the production 100k path floor.",
            "No sportsbook historical prices or closing totals are used; this audit cannot establish edge, CLV, ROI, or Truth-Gate promotion.",
        ],
        "total_run_forecast": {
            "mean_predicted_final_total": sum(predicted) / n,
            "mean_actual_final_total": sum(actual) / n,
            "mean_bias_runs_model_minus_actual": sum(errors) / n,
            "mae_runs": sum(abs_errors) / n,
            "rmse_runs": sqrt(sum(sq_errors) / n),
        },
        "over_calibration_by_reference_line": {
            str(line): _binary_summary(rows) for line, rows in line_rows.items()
        },
        "home_moneyline_calibration": _binary_summary(home_ml_rows),
        "games": game_rows,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps({
        "output": str(out),
        "games_audited": n,
        "failures": len(failures),
        "total_run_forecast": payload["total_run_forecast"],
        "home_moneyline": {k: v for k, v in payload["home_moneyline_calibration"].items() if k != "bins"},
        "reference_lines": {
            line: {k: v for k, v in summary.items() if k != "bins"}
            for line, summary in payload["over_calibration_by_reference_line"].items()
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
