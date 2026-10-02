#!/usr/bin/env python3
"""Fetch exact 2011-2015 nflverse PBP and fit frozen NFL game-script V2."""
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

from sportsedge.research.nfl_game_script_v2_fit import (
    DEVELOPMENT_SEASONS,
    EXPOSED_V1_SEASONS,
    MODEL_FIELDS,
    VALIDATION_SEASON,
    build_team_game_rows,
    expected_pbp_uri,
    fit_game_script_v2,
    load_prelock,
    validate_artifact,
)

USER_AGENT = "SportsEdge-NFL-game-script-v2/1.0"


def _fetch_exact_csv(season: int, *, temp_dir: Path) -> tuple[Path, dict[str, object]]:
    uri = expected_pbp_uri(season)
    target = temp_dir / f"play_by_play_{season}.csv"
    digest = sha256()
    byte_count = 0
    req = Request(uri, headers={"User-Agent": USER_AGENT, "Accept": "text/csv"})
    retrieved_at = datetime.now(timezone.utc)
    try:
        with urlopen(req, timeout=60) as response, target.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                byte_count += len(chunk)
    except Exception as exc:
        raise RuntimeError(f"NFL_GAME_SCRIPT_V2_SOURCE_FETCH_FAILED:{season}") from exc
    if byte_count <= 0:
        raise RuntimeError(f"NFL_GAME_SCRIPT_V2_SOURCE_EMPTY:{season}")
    return target, {
        "season": int(season),
        "source_uri": uri,
        "raw_sha256": digest.hexdigest(),
        "retrieved_at": retrieved_at.isoformat(),
        "raw_bytes": byte_count,
    }


def _project_csv(path: Path, *, expected_season: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = set(reader.fieldnames or ())
        missing = set(MODEL_FIELDS) - columns
        if missing:
            raise RuntimeError(
                f"NFL_GAME_SCRIPT_V2_SOURCE_SCHEMA_MISSING:{expected_season}:"
                + ",".join(sorted(missing))
            )
        for raw in reader:
            projected = {field: raw.get(field) for field in MODEL_FIELDS}
            raw_season = str(projected.get("season") or "").strip()
            if raw_season:
                try:
                    parsed = int(float(raw_season))
                except ValueError as exc:
                    raise RuntimeError(
                        f"NFL_GAME_SCRIPT_V2_SOURCE_SEASON_INVALID:{expected_season}"
                    ) from exc
                if parsed != expected_season:
                    raise RuntimeError(
                        f"NFL_GAME_SCRIPT_V2_SOURCE_SEASON_MISMATCH:{expected_season}:{parsed}"
                    )
            rows.append(projected)
    if not rows:
        raise RuntimeError(f"NFL_GAME_SCRIPT_V2_SOURCE_ROWS_EMPTY:{expected_season}")
    return rows


def run_fit(*, out_path: Path, summary_path: Path | None = None) -> dict[str, object]:
    prelock = load_prelock()
    fit_seasons = tuple(int(x) for x in prelock["fit_window"]["seasons"])
    if fit_seasons != DEVELOPMENT_SEASONS:
        raise RuntimeError("NFL_GAME_SCRIPT_V2_PRELOCK_WINDOW_DRIFT")
    if set(DEVELOPMENT_SEASONS) & set(EXPOSED_V1_SEASONS):
        raise RuntimeError("NFL_GAME_SCRIPT_V2_EXPOSED_V1_WINDOW_REUSE")
    if VALIDATION_SEASON in DEVELOPMENT_SEASONS:
        raise RuntimeError("NFL_GAME_SCRIPT_V2_VALIDATION_LEAK")

    team_games: list[dict[str, object]] = []
    receipts: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="sportsedge-nfl-game-script-v2-") as tmp:
        temp_dir = Path(tmp)
        for season in DEVELOPMENT_SEASONS:
            csv_path, receipt = _fetch_exact_csv(season, temp_dir=temp_dir)
            projected = _project_csv(csv_path, expected_season=season)
            reduced = build_team_game_rows(projected)
            if any(int(row["season"]) != season for row in reduced):
                raise RuntimeError(f"NFL_GAME_SCRIPT_V2_TEAM_GAME_SEASON_DRIFT:{season}")
            team_games.extend(reduced)
            receipts.append(receipt)
            csv_path.unlink(missing_ok=True)

    artifact = fit_game_script_v2(team_games, source_receipts=receipts)
    validate_artifact(artifact)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    summary = {
        "schema": "SPORTSEDGE_NFL_GAME_SCRIPT_V2_FIT_RUN_SUMMARY",
        "status": "FIT_COMPLETE_RESEARCH_ONLY_NOT_VALIDATED",
        "artifact_sha256": artifact["artifact_sha256"],
        "prelock_sha256": artifact["prelock_sha256"],
        "n_team_games": artifact["n_team_games"],
        "fit_seasons": list(DEVELOPMENT_SEASONS),
        "excluded_v1_seasons": list(EXPOSED_V1_SEASONS),
        "validation_season": VALIDATION_SEASON,
        "validation_season_accessed": False,
        "selected_alpha": artifact["alpha_selection"]["selected_alpha"],
        "source_receipts": receipts,
        "margin_grid_diagnostic": artifact["margin_grid_diagnostic"],
        "authority": artifact["authority"],
    }
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print("NFL_GAME_SCRIPT_V2_FIT_SUMMARY=" + json.dumps(summary, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="artifacts/nfl_game_script_v2/nfl_game_script_v2_fit.json",
    )
    parser.add_argument(
        "--summary-out",
        default="artifacts/nfl_game_script_v2/nfl_game_script_v2_fit_summary.json",
    )
    args = parser.parse_args()
    run_fit(
        out_path=Path(args.out),
        summary_path=Path(args.summary_out) if args.summary_out else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
