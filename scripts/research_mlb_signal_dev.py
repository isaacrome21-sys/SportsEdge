#!/usr/bin/env python3
"""Run the preregistered pre-2025 MLB score-signal development experiment.

This script deliberately cannot fetch or evaluate 2025.  It selects one feature
family on 2023 using only prior rows, then reveals 2024 once for development
confirmation.  The output is research evidence only and cannot promote a market.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fit_mlb_baseline import _canonical_sha256, _normalize_schedule_duplicates, fetch_season  # noqa: E402
from sportsedge.sports.mlb.signal_research import (  # noqa: E402
    FEATURE_FAMILIES,
    MLB_SIGNAL_CONFIRMATION_SEASON,
    MLB_SIGNAL_RESEARCH_VERSION,
    MLB_SIGNAL_SACRED_HOLDOUT_SEASON,
    MLB_SIGNAL_SELECTION_SEASON,
    MLBSignalResearchError,
    build_feature_rows,
    evaluate_predeclared_families,
    validate_research_seasons,
)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DERIVATION_SURFACE = (
    "scripts/fit_mlb_baseline.py",
    "scripts/research_mlb_signal_dev.py",
    "sportsedge/sports/mlb/signal_research.py",
)


def _derivation_sha256() -> str:
    digest = sha256()
    for relative in DERIVATION_SURFACE:
        raw = (ROOT / relative).read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return digest.hexdigest()


def _feature_row_hashes(feature_rows: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    return {family: _canonical_sha256(rows) for family, rows in sorted(feature_rows.items())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2021,2022,2023,2024")
    parser.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--out", default="artifacts/mlb_signal_dev_report.json")
    args = parser.parse_args()

    try:
        seasons = validate_research_seasons([int(value) for value in args.seasons.split(",") if value.strip()])
    except (ValueError, MLBSignalResearchError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    git_sha = str(args.git_sha or "").strip().lower()
    if git_sha and not _GIT_SHA_RE.fullmatch(git_sha):
        print("MLB_SIGNAL_DEV_GIT_SHA_INVALID", file=sys.stderr)
        return 2

    raw_games: list[dict[str, Any]] = []
    per_season: dict[str, int] = {}
    for season in seasons:
        if season >= MLB_SIGNAL_SACRED_HOLDOUT_SEASON:
            print("MLB_SIGNAL_DEV_SACRED_2025_HOLDOUT_FORBIDDEN", file=sys.stderr)
            return 2
        rows = fetch_season(season)
        per_season[str(season)] = len(rows)
        raw_games.extend(rows)
        print(f"{season}: {len(rows)} final regular-season rows", flush=True)
    if not raw_games:
        print("MLB_SIGNAL_DEV_NO_SOURCE_ROWS", file=sys.stderr)
        return 2

    ordered_raw = sorted(raw_games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    raw_sha = _canonical_sha256(ordered_raw)
    try:
        normalized_games, duplicate_normalization = _normalize_schedule_duplicates(ordered_raw)
        feature_rows = build_feature_rows(normalized_games)
        evaluation = evaluate_predeclared_families(feature_rows)
    except (ValueError, MLBSignalResearchError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    identity_rows = [
        {
            "date": row["date"],
            "season": row["season"],
            "game_pk": row["game_pk"],
            "margin": row["margin"],
            "total": row["total"],
        }
        for row in feature_rows["baseline_v1"]
    ]
    counts_by_season: dict[str, int] = {}
    for season in seasons:
        counts_by_season[str(season)] = sum(int(row["season"]) == season for row in identity_rows)

    report = {
        "schema_version": "MLB_SIGNAL_DEV_REPORT_V1",
        "research_version": MLB_SIGNAL_RESEARCH_VERSION,
        "status": "RESEARCH_ONLY_NOT_MODEL_P",
        "code_git_sha": git_sha or None,
        "derivation_code_sha256": _derivation_sha256(),
        "derivation_surface": list(DERIVATION_SURFACE),
        "source": {
            "provider": "MLB StatsAPI",
            "authentication": "NONE",
            "paid_provider_used": False,
            "requested_seasons": list(seasons),
            "per_season_raw_rows": per_season,
            "raw_row_count": len(ordered_raw),
            "raw_source_rows_sha256": raw_sha,
            "normalized_game_count": len(normalized_games),
            "normalized_source_rows_sha256": _canonical_sha256(normalized_games),
            "duplicate_normalization": duplicate_normalization,
        },
        "data_boundary": {
            "allowed_seasons": list(seasons),
            "family_selection_season": MLB_SIGNAL_SELECTION_SEASON,
            "development_confirmation_season": MLB_SIGNAL_CONFIRMATION_SEASON,
            "sacred_holdout_season": MLB_SIGNAL_SACRED_HOLDOUT_SEASON,
            "sacred_holdout_requested": False,
            "sacred_holdout_accessed": False,
            "post_2024_rows_allowed": False,
        },
        "model_rows": {
            "row_count": len(identity_rows),
            "rows_by_season": counts_by_season,
            "identity_rows_sha256": _canonical_sha256(identity_rows),
            "feature_family_rows_sha256": _feature_row_hashes(feature_rows),
        },
        "feature_families": {family: list(names) for family, names in FEATURE_FAMILIES.items()},
        "evaluation": evaluation,
        "governance": {
            "market_data_used": False,
            "model_p_created": False,
            "truth_gate_changed": False,
            "eligibility_changed": False,
            "official_bet_created": False,
            "promotion_evidence": False,
            "allowed_use": "PRE2025_FEATURE_RESEARCH_ONLY",
        },
    }

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    summary = {
        "status": report["status"],
        "raw_row_count": report["source"]["raw_row_count"],
        "normalized_game_count": report["source"]["normalized_game_count"],
        "model_row_count": report["model_rows"]["row_count"],
        "selected_family": evaluation["selected_family"],
        "confirmation_verdict": evaluation["verdict"],
        "confirmation_rmse_improvement_vs_baseline": evaluation["confirmation_rmse_improvement_vs_baseline"],
        "sacred_2025_holdout_accessed": False,
        "promotion_evidence": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
