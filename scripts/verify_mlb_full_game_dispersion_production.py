#!/usr/bin/env python3
"""Verify the audit-only MLB full-game dispersion candidate against production baseline.

Does not modify production shared_game_engine / v7_distribution. Baseline uses the
current main simulate_game_distribution path. Candidate uses the audit script's
local Gamma-Poisson PMF. No prices are used.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from scripts.audit_mlb_game_engine_dispersion import (
    REFERENCE_LINES,
    _binary_summary,
    _candidate_pmf,
    _fit_dispersion_r,
    _line_prob,
    _schedule,
    _score_distribution,
)
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource, PRODUCTION_RUN_MEAN_VERSION
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import (
    DEFAULT_EXTRA_HALF_INNING_MEAN,
    DEFAULT_FIRST_INNING_DISPERSION_R,
    DEFAULT_FIRST_INNING_SHARE,
    V7_DISTRIBUTION_VERSION,
    simulate_game_distribution,
)


def _summaries(rows: list[dict], key: str) -> dict[str, dict]:
    out = {}
    for line in REFERENCE_LINES:
        pairs = [(float(row[key][str(line)]), 1 if int(row["actual_final_total"]) > line else 0) for row in rows]
        out[str(line)] = _binary_summary(pairs)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default="2026-09-27")
    ap.add_argument("--validation-start", default="2026-09-15")
    ap.add_argument("--max-games", type=int, default=250)
    ap.add_argument("--simulations", type=int, default=100000)
    ap.add_argument("--output", default="artifacts/mlb_full_game_dispersion_production_verify.json")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    validation_start = date.fromisoformat(args.validation_start)
    if not start < validation_start <= end:
        raise SystemExit("validation-start must be inside (start, end]")
    if end >= date(2026, 9, 29):
        raise SystemExit("verification end must be strictly before 2026-09-29")
    if args.simulations < 100000:
        raise SystemExit("verification uses the production 100k simulation floor")

    games = _schedule(start, end)
    if args.max_games > 0 and len(games) > args.max_games:
        games = games[-args.max_games:]

    source = MLBAllMarketHistorySource(retrieved_at=datetime(2026, 9, 29, tzinfo=timezone.utc))
    rows = []
    failures = []
    for game in games:
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
            rows.append({
                **game,
                "run_mean_version": feature.get("run_mean_version"),
                "away_mean": float(feature["away_mean_runs"]),
                "home_mean": float(feature["home_mean_runs"]),
                "model_input_total_mean": float(feature["away_mean_runs"]) + float(feature["home_mean_runs"]),
                "actual_final_total": int(game["away_score"]) + int(game["home_score"]),
                "feature_source_hash": feature.get("source_subset_hash"),
            })
        except Exception as exc:
            failures.append({"game_pk": game.get("game_pk"), "error": f"{type(exc).__name__}: {exc}"})

    if not rows:
        raise SystemExit("no games verified")
    if {row["run_mean_version"] for row in rows} != {PRODUCTION_RUN_MEAN_VERSION}:
        raise SystemExit("verification did not bind exclusively to current production run means")

    tuning = [row for row in rows if date.fromisoformat(row["official_date"]) < validation_start]
    validation = [row for row in rows if date.fromisoformat(row["official_date"]) >= validation_start]
    fit = _fit_dispersion_r(tuning)
    locked_r = float(fit["locked_r"])

    for index, row in enumerate(validation, 1):
        away_mean = row["away_mean"]
        home_mean = row["home_mean"]
        baseline = simulate_game_distribution(
            away_mean_runs=away_mean,
            home_mean_runs=home_mean,
            total_line=0.0,
            simulations=args.simulations,
            build_hash=canonical_json_sha256({
                "engine": V7_DISTRIBUTION_VERSION,
                "verify": "baseline",
                "game_pk": row["game_pk"],
            }),
            first_inning_share=DEFAULT_FIRST_INNING_SHARE,
            first_inning_dispersion_r=DEFAULT_FIRST_INNING_DISPERSION_R,
            extra_half_inning_mean=DEFAULT_EXTRA_HALF_INNING_MEAN,
        )
        candidate_pmf = _candidate_pmf(
            away_mean=away_mean,
            home_mean=home_mean,
            dispersion_r=locked_r,
            simulations=args.simulations,
            identity=str(row["game_pk"]),
        )
        row["baseline"] = {}
        row["candidate"] = {}
        for line in REFERENCE_LINES:
            l_over, l_under, _ = _line_prob(baseline.joint_score_pmf, line)
            c_over, c_under, _ = _line_prob(candidate_pmf, line)
            row["baseline"][str(line)] = l_over / (l_over + l_under) if (l_over + l_under) > 0 else None
            row["candidate"][str(line)] = c_over / (c_over + c_under) if (c_over + c_under) > 0 else None
        print(f"[{index}/{len(validation)}] {row['game_pk']} verified")

    baseline_lines = _summaries(validation, "baseline")
    candidate_lines = _summaries(validation, "candidate")
    baseline_score = _score_distribution(baseline_lines)
    candidate_score = _score_distribution(candidate_lines)
    checks = {
        "candidate_closes_9_5_calibration_gap": abs(float(candidate_lines["9.5"]["calibration_gap_pp"])) < abs(float(baseline_lines["9.5"]["calibration_gap_pp"])),
        "candidate_improves_mean_abs_calibration_gap": float(candidate_score["mean_abs_calibration_gap_pp"]) < float(baseline_score["mean_abs_calibration_gap_pp"]),
        "candidate_noninferior_mean_brier": float(candidate_score["mean_brier"]) <= float(baseline_score["mean_brier"]),
    }
    checks["candidate_passes_all_three"] = all(checks.values())

    payload = {
        "schema_version": 1,
        "verification": "MLB_FULL_GAME_DISPERSION_AUDIT_VERIFY_V1",
        "note": "Candidate is audit-only; production shared_game_engine and v7_distribution are unchanged.",
        "production_mean_version": PRODUCTION_RUN_MEAN_VERSION,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "validation_start": validation_start.isoformat(),
        "games_requested": len(games),
        "games_loaded": len(rows),
        "tuning_games": len(tuning),
        "validation_games": len(validation),
        "failures": failures,
        "simulations_per_game_per_distribution": args.simulations,
        "dispersion_fit": fit,
        "locked_candidate_r": locked_r,
        "baseline": baseline_lines,
        "candidate": candidate_lines,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "checks": checks,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps({
        "output": str(out),
        "dispersion_fit": fit,
        "baseline": baseline_lines,
        "candidate": candidate_lines,
        "checks": checks,
    }, indent=2))
    # Research gate only: do not fail the job on candidate performance; numbers are the product.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
