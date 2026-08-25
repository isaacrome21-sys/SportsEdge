#!/usr/bin/env python3
"""Produce hash-bound NFL schedule-score challenger evidence.

This runner is intentionally not the production NFL M2. It evaluates a simple,
diagnosable rolling score-state challenger from schedule/results data only. Its
evidence is useful as a benchmark and pipeline exercise but is explicitly
identity-incompatible with the production M2 promotion registry.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen

from sportsedge.core.validation.football_evidence import (
    FootballValidationBundle,
    build_promotion_evidence,
    validate_real_history_bundle,
)
from sportsedge.sports.nfl.history import NFLVERSE_SCHEDULE_CSV, normalize_nfl_rows, parse_schedule_csv
from sportsedge.sports.nfl.historical_validation import (
    build_calibration_evidence,
    build_nfl_fold_rows,
    build_nfl_game_evaluations,
    calibrate_nfl_evaluations,
)

SCHEDULE_CHALLENGER_MODEL_ID = "nfl_schedule_score_challenger_v1"
SCHEDULE_CHALLENGER_FEATURE_CONTRACT = "NFL_SCHEDULE_SCORE_CHALLENGER_V1"


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "SportsEdge-NFL-validation/1.0"})
    with urlopen(req, timeout=45) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=NFLVERSE_SCHEDULE_CSV)
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--start-season", type=int, default=2006)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--min-history-seasons", type=int, default=2)
    parser.add_argument("--min-calibration-fit-seasons", type=int, default=2)
    parser.add_argument("--calibration-bins", type=int, default=10)
    parser.add_argument("--calibration-min-bin-n", type=int, default=25)
    parser.add_argument("--calibration-threshold", type=float, default=0.05)
    parser.add_argument("--ewma-alpha", type=float, default=0.18)
    parser.add_argument("--home-field-points", type=float, default=1.7)
    parser.add_argument("--margin-sigma", type=float, default=13.5)
    parser.add_argument("--total-sigma", type=float, default=13.0)
    parser.add_argument("--fold-win-threshold", type=float, default=0.65)
    parser.add_argument("--out", type=Path, default=Path("artifacts/nfl_schedule_challenger_validation.json"))
    args = parser.parse_args()

    if args.end_season < args.start_season:
        raise SystemExit("END_SEASON_BEFORE_START_SEASON")
    if not 0.0 < args.fold_win_threshold <= 1.0:
        raise SystemExit("FOLD_WIN_THRESHOLD_INVALID")

    raw = args.source_file.read_bytes() if args.source_file is not None else _fetch(args.source_url)
    source_hash = sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig")
    seasons = range(args.start_season, args.end_season + 1)
    history_rows = normalize_nfl_rows(parse_schedule_csv(text), seasons)
    raw_evaluations = build_nfl_game_evaluations(
        history_rows,
        min_history_seasons=args.min_history_seasons,
        ewma_alpha=args.ewma_alpha,
        home_field_points=args.home_field_points,
        margin_sigma=args.margin_sigma,
        total_sigma=args.total_sigma,
    )
    evaluations = calibrate_nfl_evaluations(
        raw_evaluations,
        min_fit_seasons=args.min_calibration_fit_seasons,
    )
    folds = build_nfl_fold_rows(evaluations, require_calibrated=True)
    calibration = build_calibration_evidence(
        evaluations,
        bins=args.calibration_bins,
        min_bin_n=args.calibration_min_bin_n,
        max_bin_deviation_threshold=args.calibration_threshold,
    )

    validation_rows = [
        {
            "season": int(row["season"]),
            "market": str(row["market"]),
            "m1_log_loss": float(row["m1_log_loss"]),
            "m2_log_loss": float(row["m2_log_loss"]),
        }
        for row in folds
    ]
    bundle = FootballValidationBundle(
        sport="nfl",
        provenance="real",
        source_uri=args.source_url,
        source_sha256=source_hash,
        rows=validation_rows,
    )
    validated = validate_real_history_bundle(bundle)
    promotion = build_promotion_evidence(validated)

    per_market = {}
    for market, evidence in promotion.items():
        record = asdict(evidence)
        record["challenger_fold_gate_pass"] = bool(
            evidence.fold_total > 0 and evidence.fold_win_rate >= args.fold_win_threshold
        )
        record["required_fold_win_rate"] = args.fold_win_threshold
        record["calibration"] = calibration.get(market)
        per_market[market] = record

    payload = {
        "schema_version": 3,
        "model_id": SCHEDULE_CHALLENGER_MODEL_ID,
        "feature_contract": SCHEDULE_CHALLENGER_FEATURE_CONTRACT,
        "promotion_eligible_model": False,
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_url": args.source_url,
        "source_sha256": source_hash,
        "source_transport": "FROZEN_LOCAL_BYTES" if args.source_file is not None else "LIVE_FETCH",
        "season_range": [args.start_season, args.end_season],
        "history_row_count": len(history_rows),
        "raw_evaluation_game_count": len(raw_evaluations),
        "calibrated_evaluation_game_count": sum(
            row.get("m2_home_cover_calibrated_prob") is not None
            or row.get("m2_over_calibrated_prob") is not None
            for row in evaluations
        ),
        "fold_count": len(folds),
        "parameters": {
            "min_history_seasons": args.min_history_seasons,
            "min_calibration_fit_seasons": args.min_calibration_fit_seasons,
            "calibration_bins": args.calibration_bins,
            "calibration_min_bin_n": args.calibration_min_bin_n,
            "calibration_threshold": args.calibration_threshold,
            "ewma_alpha": args.ewma_alpha,
            "home_field_points": args.home_field_points,
            "margin_sigma": args.margin_sigma,
            "total_sigma": args.total_sigma,
        },
        "folds": folds,
        "calibration_evidence": calibration,
        "promotion_evidence": per_market,
        "promotion_note": (
            "This is schedule-only challenger evidence and cannot promote the production NFL M2. "
            "Fold losses use isotonic probabilities calibrated strictly on prior seasons."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
