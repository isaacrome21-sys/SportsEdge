#!/usr/bin/env python3
"""Spend the single frozen 2025 NFL game-script V2 validation look."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.research.nfl_game_script_v2_validate_2025 import (
    MODEL_FIELDS,
    VALIDATION_SEASON,
    build_validation_team_games,
    expected_validation_uri,
    load_validation_lock,
    validate_2025,
)

USER_AGENT = "SportsEdge-NFL-game-script-v2-validation/1.0"


def _fetch_2025(temp_dir: Path) -> tuple[Path, dict[str, object]]:
    uri = expected_validation_uri()
    target = temp_dir / "play_by_play_2025.csv"
    digest = sha256()
    size = 0
    retrieved = datetime.now(timezone.utc)
    req = Request(uri, headers={"User-Agent": USER_AGENT, "Accept": "text/csv"})
    try:
        with urlopen(req, timeout=60) as response, target.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except Exception as exc:
        raise RuntimeError("NFL_GAME_SCRIPT_V2_2025_FETCH_FAILED") from exc
    if size <= 0:
        raise RuntimeError("NFL_GAME_SCRIPT_V2_2025_SOURCE_EMPTY")
    return target, {
        "season": VALIDATION_SEASON,
        "source_uri": uri,
        "raw_sha256": digest.hexdigest(),
        "retrieved_at": retrieved.isoformat(),
        "raw_bytes": size,
    }


def _read_projected(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = set(reader.fieldnames or ())
        missing = set(MODEL_FIELDS) - columns
        if missing:
            raise RuntimeError(
                "NFL_GAME_SCRIPT_V2_2025_SCHEMA_MISSING:"
                + ",".join(sorted(missing))
            )
        for raw in reader:
            projected = {field: raw.get(field) for field in MODEL_FIELDS}
            raw_season = str(projected.get("season") or "").strip()
            if raw_season:
                parsed = int(float(raw_season))
                if parsed != VALIDATION_SEASON:
                    raise RuntimeError(
                        f"NFL_GAME_SCRIPT_V2_2025_SOURCE_SEASON_MISMATCH:{parsed}"
                    )
            rows.append(projected)
    if not rows:
        raise RuntimeError("NFL_GAME_SCRIPT_V2_2025_SOURCE_ROWS_EMPTY")
    return rows


def run_validation(
    *,
    out_path: Path,
    summary_path: Path,
) -> dict[str, object]:
    # This is deliberately before target-source access.
    lock = load_validation_lock()

    with tempfile.TemporaryDirectory(
        prefix="sportsedge-nfl-game-script-v2-2025-"
    ) as tmp:
        source_path, source_receipt = _fetch_2025(Path(tmp))
        projected = _read_projected(source_path)
        team_games = build_validation_team_games(projected)
        source_path.unlink(missing_ok=True)

    artifact = validate_2025(
        team_games,
        source_receipt=source_receipt,
        lock=lock,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    metrics = artifact["metrics"]
    summary: dict[str, object] = {
        "schema": "SPORTSEDGE_NFL_GAME_SCRIPT_V2_2025_VALIDATION_SUMMARY",
        "status": artifact["status"],
        "validation_window_spent": True,
        "validation_season": VALIDATION_SEASON,
        "canonical_fit_artifact_sha256": artifact[
            "canonical_fit_artifact_sha256"
        ],
        "validation_artifact_sha256": artifact["artifact_sha256"],
        "source_receipt": artifact["source_receipt"],
        "n_teams": artifact["n_teams"],
        "n_evaluated_team_games": artifact["n_evaluated_team_games"],
        "evaluated_weeks": artifact["evaluated_weeks"],
        "baseline": metrics["baseline"],
        "scripted": metrics["scripted"],
        "combined_mae_relative_improvement": metrics[
            "combined_mae_relative_improvement"
        ],
        "gates": metrics["gates"],
        "passed": metrics["passed"],
        "post_result_policy": artifact["post_result_policy"],
        "authority": artifact["authority"],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        "NFL_GAME_SCRIPT_V2_2025_VALIDATION="
        + json.dumps(summary, sort_keys=True)
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=(
            "artifacts/nfl_game_script_v2/"
            "nfl_game_script_v2_2025_validation.json"
        ),
    )
    parser.add_argument(
        "--summary-out",
        default=(
            "artifacts/nfl_game_script_v2/"
            "nfl_game_script_v2_2025_validation_summary.json"
        ),
    )
    args = parser.parse_args()
    run_validation(
        out_path=Path(args.out),
        summary_path=Path(args.summary_out),
    )
    # A model-gate FAIL is a valid completed one-look result, not a CI error.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
