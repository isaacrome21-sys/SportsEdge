#!/usr/bin/env python3
"""Fit/evaluate a development-only NFL play-level research model.

Inputs:
- hash-bound NFL play-level artifact containing feature_rows
- game labels CSV with season, game_id, home_team, away_team, home_score, away_score

Fits 2021-23 only, evaluates 2024 only, performs leave-one-feature-out ablations,
and emits research metrics. It never emits bettor-facing Model_P.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from sportsedge.research_diagnostics import ablation_delta, regression_metrics
from sportsedge.sports.nfl.research_game_model import FEATURE_NAMES, fit_ridge, game_vector, predict_ridge

DEV = {2021, 2022, 2023}
VAL = 2024


def load_labels(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [dict(r) for r in csv.DictReader(fh)]
    required = {"season", "game_id", "home_team", "away_team", "home_score", "away_score"}
    if not rows or not required.issubset(rows[0]):
        raise SystemExit("NFL_RESEARCH_LABEL_SCHEMA_INVALID")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--alpha", type=float, default=1.0)
    args = ap.parse_args()

    artifact = json.loads(Path(args.features).read_text(encoding="utf-8"))
    if artifact.get("status") != "RESEARCH_ONLY_NO_MODEL_P_AUTHORITY":
        raise SystemExit("NFL_RESEARCH_FEATURE_ARTIFACT_NOT_RESEARCH_ONLY")
    if artifact.get("splits", {}).get("2025_used") is not False or artifact.get("splits", {}).get("2026_used") is not False:
        raise SystemExit("NFL_RESEARCH_FEATURE_ARTIFACT_EXPOSED_FUTURE_SEASON")
    rows = artifact.get("feature_rows")
    if not isinstance(rows, list) or not rows:
        raise SystemExit("NFL_RESEARCH_FEATURE_ROWS_REQUIRED")

    by_key = {(int(r["season"]), str(r["game_id"]), str(r["team"])): r for r in rows}
    labels = load_labels(Path(args.labels))

    assembled = []
    for r in labels:
        season = int(r["season"])
        if season not in DEV | {VAL}:
            raise SystemExit(f"NFL_RESEARCH_LABEL_SEASON_NOT_ALLOWED:{season}")
        gid = str(r["game_id"])
        home = by_key.get((season, gid, str(r["home_team"])))
        away = by_key.get((season, gid, str(r["away_team"])))
        if home is None or away is None:
            continue
        hscore, ascore = float(r["home_score"]), float(r["away_score"])
        assembled.append({
            "season": season,
            "game_id": gid,
            "home_team": str(r["home_team"]),
            "away_team": str(r["away_team"]),
            "x": game_vector(home, away),
            "margin": hscore - ascore,
            "total": hscore + ascore,
        })

    dev = [r for r in assembled if r["season"] in DEV]
    val = [r for r in assembled if r["season"] == VAL]
    if len(dev) < len(FEATURE_NAMES) + 2:
        raise SystemExit("NFL_RESEARCH_DEV_SAMPLE_TOO_SMALL")
    if not val:
        raise SystemExit("NFL_RESEARCH_VALIDATION_SAMPLE_MISSING")

    x_dev = [r["x"] for r in dev]
    x_val = [r["x"] for r in val]
    y_margin_dev = [r["margin"] for r in dev]
    y_margin_val = [r["margin"] for r in val]
    y_total_dev = [r["total"] for r in dev]
    y_total_val = [r["total"] for r in val]

    margin_coef = fit_ridge(x_dev, y_margin_dev, alpha=args.alpha)
    total_coef = fit_ridge(x_dev, y_total_dev, alpha=args.alpha)
    margin_metrics = regression_metrics(predict_ridge(margin_coef, x_val), y_margin_val)
    total_metrics = regression_metrics(predict_ridge(total_coef, x_val), y_total_val)

    ablations = {}
    for drop_idx, drop_name in enumerate(FEATURE_NAMES):
        x_dev_ab = [[v for i, v in enumerate(row) if i != drop_idx] for row in x_dev]
        x_val_ab = [[v for i, v in enumerate(row) if i != drop_idx] for row in x_val]
        mc = fit_ridge(x_dev_ab, y_margin_dev, alpha=args.alpha)
        tc = fit_ridge(x_dev_ab, y_total_dev, alpha=args.alpha)
        mm = regression_metrics(predict_ridge(mc, x_val_ab), y_margin_val)
        tm = regression_metrics(predict_ridge(tc, x_val_ab), y_total_val)
        ablations[drop_name] = {
            "margin_metrics": mm,
            "total_metrics": tm,
            "margin_delta_vs_full": ablation_delta(margin_metrics, mm),
            "total_delta_vs_full": ablation_delta(total_metrics, tm),
        }

    output = {
        "schema": "NFL_PLAY_LEVEL_GAME_MODEL_RESEARCH_V1",
        "status": "RESEARCH_ONLY_NO_MODEL_P_AUTHORITY",
        "splits": {"development": [2021, 2022, 2023], "validation": 2024, "2025_used": False, "2026_used": False},
        "model": {"family": "RIDGE_LINEAR_RESEARCH", "alpha": args.alpha, "feature_names": list(FEATURE_NAMES)},
        "sample": {"development_games": len(dev), "validation_games": len(val)},
        "validation": {"margin": margin_metrics, "total": total_metrics},
        "ablations": ablations,
        "governance": {
            "research_only": True,
            "model_p_created": False,
            "promotion_authority": False,
            "truth_gate_authority": False,
            "official_bet_authority": False,
            "market_prices_used_as_features": False,
            "prop_engine_authority": False,
            "2025_reused_as_fresh_holdout": False,
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "development_games": len(dev), "validation_games": len(val), "output": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
