#!/usr/bin/env python3
"""Fit NFL game-script V2 from exact 2011-2015 nflverse CSV sources only."""
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
    FIT_SEASONS,
    MODEL_FIELDS,
    VALIDATION_SEASON,
    build_team_game_rows,
    expected_pbp_uri,
    fit_game_script_v2,
    load_prelock,
    validate_artifact,
)

USER_AGENT = "SportsEdge-NFL-game-script-v2/1.0"


def _fetch(season: int, temp_dir: Path) -> tuple[Path, dict[str, object]]:
    uri = expected_pbp_uri(season)
    target = temp_dir / f"play_by_play_{season}.csv"
    digest = sha256()
    size = 0
    req = Request(uri, headers={"User-Agent": USER_AGENT, "Accept": "text/csv"})
    retrieved = datetime.now(timezone.utc)
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
        raise RuntimeError(f"NFL_GAME_SCRIPT_V2_FETCH_FAILED:{season}") from exc
    if size <= 0:
        raise RuntimeError(f"NFL_GAME_SCRIPT_V2_SOURCE_EMPTY:{season}")
    return target, {
        "season": season,
        "source_uri": uri,
        "raw_sha256": digest.hexdigest(),
        "retrieved_at": retrieved.isoformat(),
        "raw_bytes": size,
    }


def _read_projected(path: Path, season: int) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = set(reader.fieldnames or ())
        missing = set(MODEL_FIELDS) - columns
        if missing:
            raise RuntimeError(
                f"NFL_GAME_SCRIPT_V2_SCHEMA_MISSING:{season}:"
                + ",".join(sorted(missing))
            )
        for raw in reader:
            projected = {field: raw.get(field) for field in MODEL_FIELDS}
            raw_season = str(projected.get("season") or "").strip()
            if raw_season:
                parsed = int(float(raw_season))
                if parsed != season:
                    raise RuntimeError(
                        f"NFL_GAME_SCRIPT_V2_SOURCE_SEASON_MISMATCH:{season}:{parsed}"
                    )
            out.append(projected)
    if not out:
        raise RuntimeError(f"NFL_GAME_SCRIPT_V2_SOURCE_ROWS_EMPTY:{season}")
    return out


def run_fit(out_path: Path, summary_path: Path) -> dict[str, object]:
    prelock = load_prelock()
    if FIT_SEASONS != (2011, 2012, 2013, 2014, 2015):
        raise RuntimeError("NFL_GAME_SCRIPT_V2_FIT_WINDOW_DRIFT")
    if VALIDATION_SEASON != 2025 or VALIDATION_SEASON in FIT_SEASONS:
        raise RuntimeError("NFL_GAME_SCRIPT_V2_VALIDATION_BOUNDARY_DRIFT")
    if prelock["validation_window"]["status"] != "CLEAN_UNUSED_BY_V1":
        raise RuntimeError("NFL_GAME_SCRIPT_V2_VALIDATION_STATUS_DRIFT")

    team_games: list[dict[str, object]] = []
    receipts: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="sportsedge-nfl-script-v2-") as tmp:
        temp_dir = Path(tmp)
        for season in FIT_SEASONS:
            source, receipt = _fetch(season, temp_dir)
            rows = _read_projected(source, season)
            reduced = build_team_game_rows(rows)
            if any(int(row["season"]) != season for row in reduced):
                raise RuntimeError(f"NFL_GAME_SCRIPT_V2_REDUCED_SEASON_DRIFT:{season}")
            team_games.extend(reduced)
            receipts.append(receipt)
            source.unlink(missing_ok=True)

    artifact = fit_game_script_v2(team_games, source_receipts=receipts)
    validate_artifact(artifact)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    summary: dict[str, object] = {
        "schema": "SPORTSEDGE_NFL_GAME_SCRIPT_V2_FIT_RUN_SUMMARY",
        "status": "FIT_COMPLETE_RESEARCH_ONLY_NOT_VALIDATED",
        "artifact_sha256": artifact["artifact_sha256"],
        "prelock_sha256": artifact["prelock_sha256"],
        "fit_seasons": list(FIT_SEASONS),
        "validation_season": VALIDATION_SEASON,
        "validation_season_accessed": False,
        "n_team_games": artifact["n_team_games"],
        "selected_alpha": artifact["cv"]["selected_alpha"],
        "cv": artifact["cv"]["rows"],
        "probe": artifact["probe_minus35_to_plus35"],
        "source_receipts": artifact["source_receipts"],
        "authority": artifact["authority"],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("NFL_GAME_SCRIPT_V2_FIT_SUMMARY=" + json.dumps(summary, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/nfl_game_script_v2/nfl_game_script_v2_fit.json")
    parser.add_argument("--summary-out", default="artifacts/nfl_game_script_v2/nfl_game_script_v2_fit_summary.json")
    args = parser.parse_args()
    run_fit(Path(args.out), Path(args.summary_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
