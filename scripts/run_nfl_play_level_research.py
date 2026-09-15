#!/usr/bin/env python3
"""Build a PIT-safe NFL play-level research artifact from historical play rows.

This is deliberately NOT a model fitter and has no production authority. It accepts
CSV or JSONL rows, derives prior-game-only team features through 2024, and emits a
hash-bound research artifact with development/validation summaries and shadow drift.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from sportsedge.research_diagnostics import population_stability_index
from sportsedge.sports.nfl.research_play_level import build_lagged_team_game_features

DEV_SEASONS = {2021, 2022, 2023}
VALIDATION_SEASON = 2024
FEATURES = [
    "lagged_epa_per_play",
    "lagged_pass_epa_per_play",
    "lagged_rush_epa_per_play",
    "lagged_success_rate",
    "lagged_explosive_play_rate",
    "lagged_early_down_pass_rate",
    "lagged_sack_rate_allowed",
    "lagged_turnover_rate",
    "lagged_qb_cpoe",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    if suffix in {".jsonl", ".ndjson"}:
        rows = []
        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                text = line.strip()
                if not text:
                    continue
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise SystemExit(f"NFL_RESEARCH_ROW_NOT_OBJECT:{line_no}")
                rows.append(value)
        return rows
    raise SystemExit("NFL_RESEARCH_INPUT_FORMAT_UNSUPPORTED")


def summarize(values: Iterable[float]) -> dict[str, float | int | None]:
    xs = [float(v) for v in values]
    if not xs:
        return {"n": 0, "mean": None, "min": None, "max": None}
    return {
        "n": len(xs),
        "mean": sum(xs) / len(xs),
        "min": min(xs),
        "max": max(xs),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Historical nflverse-style CSV/JSONL play rows")
    ap.add_argument("--output", required=True, help="Research artifact JSON path")
    ap.add_argument("--window-games", type=int, default=6)
    ap.add_argument("--include-feature-rows", action="store_true")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.is_file():
        raise SystemExit("NFL_RESEARCH_INPUT_NOT_FOUND")

    rows = load_rows(src)
    if not rows:
        raise SystemExit("NFL_RESEARCH_INPUT_EMPTY")

    features = build_lagged_team_game_features(rows, window_games=args.window_games)
    feature_rows = [asdict(x) for x in features]
    dev = [r for r in feature_rows if r["season"] in DEV_SEASONS]
    val = [r for r in feature_rows if r["season"] == VALIDATION_SEASON]
    other = sorted({r["season"] for r in feature_rows if r["season"] not in DEV_SEASONS | {VALIDATION_SEASON}})
    if other:
        raise SystemExit(f"NFL_RESEARCH_OUTPUT_SEASON_NOT_ALLOWED:{other}")
    if not dev:
        raise SystemExit("NFL_RESEARCH_DEVELOPMENT_ROWS_MISSING")
    if not val:
        raise SystemExit("NFL_RESEARCH_VALIDATION_2024_ROWS_MISSING")

    drift: dict[str, dict[str, Any]] = {}
    stats: dict[str, dict[str, Any]] = {}
    for name in FEATURES:
        dev_values = [r[name] for r in dev]
        val_values = [r[name] for r in val]
        stats[name] = {
            "development": summarize(dev_values),
            "validation_2024": summarize(val_values),
        }
        try:
            psi = population_stability_index(dev_values, val_values, bins=10)
            drift[name] = {"psi": psi, "status": "MEASURED_SHADOW_ONLY"}
        except ValueError as exc:
            drift[name] = {"psi": None, "status": "UNAVAILABLE", "reason": str(exc)}

    artifact: dict[str, Any] = {
        "schema": "NFL_PLAY_LEVEL_RESEARCH_ARTIFACT_V1",
        "status": "RESEARCH_ONLY_NO_MODEL_P_AUTHORITY",
        "source": {
            "path": str(src),
            "sha256": sha256_file(src),
            "raw_row_count": len(rows),
        },
        "window_games": args.window_games,
        "feature_contract": "config/research/nfl_play_level_feature_contract_v1.json",
        "methodology": "config/research/model_research_methodology_v1.json",
        "splits": {
            "development_seasons": sorted(DEV_SEASONS),
            "development_feature_rows": len(dev),
            "validation_season": VALIDATION_SEASON,
            "validation_feature_rows": len(val),
            "2025_used": False,
            "2026_used": False,
        },
        "feature_statistics": stats,
        "drift_shadow": drift,
        "governance": {
            "research_only": True,
            "model_p_created": False,
            "market_prices_used_as_features": False,
            "promotion_authority": False,
            "truth_gate_authority": False,
            "official_bet_authority": False,
            "prop_engine_authority": False,
            "capture_backfill_performed": False,
        },
    }
    if args.include_feature_rows:
        artifact["feature_rows"] = feature_rows

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": artifact["status"],
        "output": str(out),
        "development_feature_rows": len(dev),
        "validation_feature_rows": len(val),
        "source_sha256": artifact["source"]["sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
