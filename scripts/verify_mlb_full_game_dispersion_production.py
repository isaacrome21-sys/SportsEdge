#!/usr/bin/env python3
"""Verify the frozen MLB full-game dispersion with the production simulator.

The tuning slice only re-derives the frozen r from strict-prior production means
and final scores. The later validation slice then compares the legacy production
simulator against the exact new production Gamma-Poisson code path. No prices are
used.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from scripts.audit_mlb_game_engine_dispersion import (
    REFERENCE_LINES,
    _binary_summary,
    _fit_dispersion_r,
    _line_prob,
    _schedule,
    _score_distribution,
)
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource, PRODUCTION_RUN_MEAN_VERSION
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import (
    DEFAULT_FULL_GAME_DISPERSION_R,
    FULL_GAME_MODE_LEGACY_LOGNORMAL,
    FULL_GAME_MODE_SHARED_GAMMA_POISSON,
    LEGACY_SHARED_GAME_SIGMA,
    LEGACY_TEAM_SIGMA,
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
    if abs(float(fit["locked_r"]) - DEFAULT_FULL_GAME_DISPERSION_R) > 1e-12:
        raise SystemExit(
            f"frozen production r drifted: fit={fit['locked_r']} production={DEFAULT_FULL_GAME_DISPERSION_R}"
        )

    for index, row in enumerate(validation, 1):
        common = dict(
            away_mean_runs=row["away_mean"],
            home_mean_runs=row["home_mean"],
            total_line=0.0,
            simulations=args.simulations,
        )
        legacy = simulate_game_distribution(
            **common,
            build_hash=canonical_json_sha256({"verify": "legacy", "game_pk": row["game_pk"]}),
            shared_game_sigma=LEGACY_SHARED_GAME_SIGMA,
            team_sigma=LEGACY_TEAM_SIGMA,
            full_game_dispersion_r=None,
        )
        candidate = simulate_game_distribution(
            **common,
            build_hash=canonical_json_sha256({"verify": "production", "game_pk": row["game_pk"]}),
            shared_game_sigma=0.0,
            team_sigma=0.0,
            full_game_dispersion_r=DEFAULT_FULL_GAME_DISPERSION_R,
        )
        if legacy.full_game_distribution_mode != FULL_GAME_MODE_LEGACY_LOGNORMAL:
            raise SystemExit("legacy verification path did not select legacy mode")
        if candidate.full_game_distribution_mode != FULL_GAME_MODE_SHARED_GAMMA_POISSON:
            raise SystemExit("production verification path did not select Gamma-Poisson mode")
        row["legacy"] = {}
        row["production"] = {}
        for line in REFERENCE_LINES:
            l_over, l_under, _ = _line_prob(legacy.joint_score_pmf, line)
            p_over, p_under, _ = _line_prob(candidate.joint_score_pmf, line)
            row["legacy"][str(line)] = l_over / (l_over + l_under)
            row["production"][str(line)] = p_over / (p_over + p_under)
        print(f"[{index}/{len(validation)}] {row['game_pk']} verified")

    baseline = _summaries(validation, "legacy")
    production = _summaries(validation, "production")
    baseline_score = _score_distribution(baseline)
    production_score = _score_distribution(production)
    checks = {
        "production_closes_9_5_calibration_gap": abs(float(production["9.5"]["calibration_gap_pp"])) < abs(float(baseline["9.5"]["calibration_gap_pp"])),
        "production_improves_mean_abs_calibration_gap": float(production_score["mean_abs_calibration_gap_pp"]) < float(baseline_score["mean_abs_calibration_gap_pp"]),
        "production_noninferior_mean_brier": float(production_score["mean_brier"]) <= float(baseline_score["mean_brier"]),
    }
    checks["production_passes_all_three"] = all(checks.values())

    payload = {
        "schema_version": 1,
        "verification": "MLB_FULL_GAME_DISPERSION_PRODUCTION_VERIFY_V1",
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
        "frozen_production_r": DEFAULT_FULL_GAME_DISPERSION_R,
        "legacy": baseline,
        "production": production,
        "legacy_score": baseline_score,
        "production_score": production_score,
        "checks": checks,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps({
        "output": str(out),
        "dispersion_fit": fit,
        "legacy": baseline,
        "production": production,
        "checks": checks,
    }, indent=2))
    if not checks["production_passes_all_three"]:
        raise SystemExit("production dispersion failed frozen validation checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
