#!/usr/bin/env python3
"""Expanding-season robustness check for the pre-2025 MLB starter hypothesis.

This is development-only evidence. It reuses the V3 source/feature builder and
compares baseline_v1 vs pit_starter_v3 in forward validation seasons 2022,
2023, and 2024. 2025 is never requested or accepted.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fit_mlb_baseline import _canonical_sha256, _normalize_schedule_duplicates  # noqa: E402
from scripts.fit_mlb_development import evaluate, select_alpha  # noqa: E402
from scripts.fit_mlb_development_v3 import (  # noqa: E402
    DEFAULT_SEASONS,
    build_v3_feature_sets,
    fetch_season_with_starters,
)

VALIDATION_SEASONS = (2022, 2023, 2024)
DERIVATION_SURFACE = (
    "scripts/fit_mlb_baseline.py",
    "scripts/fit_mlb_development.py",
    "scripts/fit_mlb_development_v3.py",
    "scripts/validate_mlb_development_v3_robustness.py",
)


def _derivation_sha256() -> str:
    digest = sha256()
    for relative in DERIVATION_SURFACE:
        raw = (ROOT / relative).read_bytes()
        digest.update(relative.encode()); digest.update(b"\0")
        digest.update(raw); digest.update(b"\0")
    return digest.hexdigest()


def build_robustness_report(
    feature_sets: dict[str, tuple[np.ndarray, list[str]]],
    margin: np.ndarray,
    total: np.ndarray,
    dates: list[str],
    game_pks: list[int],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for target_name, target in (("margin", margin), ("total", total)):
        seasons: dict[str, Any] = {}
        improvements: list[float] = []
        for validation_season in VALIDATION_SEASONS:
            train_mask = np.asarray([int(date[:4]) < validation_season for date in dates])
            valid_mask = np.asarray([int(date[:4]) == validation_season for date in dates])
            train_dates = [date for date, flag in zip(dates, train_mask) if bool(flag)]
            if int(train_mask.sum()) < 500 or int(valid_mask.sum()) < 200:
                raise SystemExit(f"MLB_DEV_V3_ROBUSTNESS_SPLIT_INSUFFICIENT:{validation_season}")
            family_metrics: dict[str, Any] = {}
            for family in ("baseline_v1", "pit_starter_v3"):
                X, _ = feature_sets[family]
                X_train, X_valid = X[train_mask], X[valid_mask]
                y_train, y_valid = target[train_mask], target[valid_mask]
                alpha, alpha_policy = select_alpha(X_train, y_train, train_dates)
                metrics = evaluate(X_train, y_train, X_valid, y_valid, alpha)
                family_metrics[family] = {
                    "selected_alpha": alpha,
                    "alpha_selection": alpha_policy,
                    "rmse": metrics["rmse"],
                    "mae": metrics["mae"],
                    "r2_vs_mean": metrics["r2_vs_mean"],
                }
            improvement = float(
                family_metrics["baseline_v1"]["rmse"] - family_metrics["pit_starter_v3"]["rmse"]
            )
            improvements.append(improvement)
            seasons[str(validation_season)] = {
                "train_seasons": sorted({int(date[:4]) for date, flag in zip(dates, train_mask) if bool(flag)}),
                "train_row_count": int(train_mask.sum()),
                "validation_row_count": int(valid_mask.sum()),
                "feature_sets": family_metrics,
                "starter_rmse_improvement_vs_baseline": improvement,
                "starter_wins": bool(improvement > 0),
            }
        results[target_name] = {
            "validation_seasons": seasons,
            "starter_win_count": sum(value > 0 for value in improvements),
            "validation_season_count": len(improvements),
            "mean_rmse_improvement_vs_baseline": float(np.mean(improvements)),
            "median_rmse_improvement_vs_baseline": float(np.median(improvements)),
            "min_rmse_improvement_vs_baseline": float(min(improvements)),
            "max_rmse_improvement_vs_baseline": float(max(improvements)),
            "all_forward_seasons_improve": bool(all(value > 0 for value in improvements)),
        }
    return {
        "schema": "MLB_DEVELOPMENT_V3_ROBUSTNESS_V1",
        "status": "RESEARCH_ONLY_NOT_MODEL_P",
        "validation_design": "EXPANDING_SEASON_FORWARD_2022_2024",
        "source_row_identity_sha256": _canonical_sha256([
            {"date": date, "game_pk": int(pk)} for date, pk in zip(dates, game_pks)
        ]),
        "derivation_code_sha256": _derivation_sha256(),
        "targets": results,
        "sacred_2025_accessed": False,
        "promotion_changed": False,
        "truth_gate_evidence": False,
        "official_evidence": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/mlb_development_v3_robustness.json")
    args = parser.parse_args()

    raw: list[dict[str, Any]] = []
    for season in DEFAULT_SEASONS:
        if season >= 2025:
            raise SystemExit("MLB_DEV_V3_ROBUSTNESS_POST_2024_FORBIDDEN")
        raw.extend(fetch_season_with_starters(season))
    canonical, _ = _normalize_schedule_duplicates(
        sorted(raw, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    )
    feature_sets, margin, total, dates, game_pks, _ = build_v3_feature_sets(canonical)
    report = build_robustness_report(feature_sets, margin, total, dates, game_pks)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        target: {
            "starter_win_count": report["targets"][target]["starter_win_count"],
            "mean_rmse_improvement_vs_baseline": report["targets"][target]["mean_rmse_improvement_vs_baseline"],
            "all_forward_seasons_improve": report["targets"][target]["all_forward_seasons_improve"],
        }
        for target in ("margin", "total")
    }, sort_keys=True))
    print("RESEARCH ONLY / FORWARD DEVELOPMENT 2022-2024 / 2025 NOT ACCESSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
