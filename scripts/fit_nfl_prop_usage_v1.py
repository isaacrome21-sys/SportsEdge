#!/usr/bin/env python3
"""Fit frozen NFL prop usage V1 using 2021-2024 development data only."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.research.nfl_prop_usage_v1_fit import (
    DEV_SEASONS,
    build_attempt9_team_environment,
    fit_prop_usage_v1,
    load_freeze,
    validate_artifact,
)

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
PLAYER_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/player_stats/"
    "player_stats_{season}.csv"
)
USER_AGENT = "SportsEdge-NFL-prop-usage-v1-fit/1.0"


def _fetch(url: str) -> tuple[bytes, dict[str, object]]:
    if "2025" in url:
        raise RuntimeError("PROP_V1_FIT_2025_SOURCE_FORBIDDEN")
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv"})
    with urlopen(req, timeout=120) as response:
        raw = response.read()
    if not raw:
        raise RuntimeError(f"PROP_V1_FIT_SOURCE_EMPTY:{url}")
    return raw, {
        "url": url,
        "bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def _csv_rows(raw: bytes) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise RuntimeError("PROP_V1_FIT_CSV_EMPTY")
    return rows


def _build_attempt9_runtime(temp_dir: Path) -> dict:
    output = temp_dir / "attempt9.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_nfl_attempt9_runtime_artifact.py"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    artifact = json.loads(output.read_text())
    if artifact.get("status") != "RECONSTRUCTED_FROZEN_OWNER_RUNTIME_NOT_MODEL_P":
        raise RuntimeError("PROP_V1_ATTEMPT9_RUNTIME_STATUS_INVALID")
    digest = str(artifact.get("artifact_sha256") or "")
    if len(digest) != 64:
        raise RuntimeError("PROP_V1_ATTEMPT9_RUNTIME_SHA_MISSING")
    return artifact


def run_fit(*, out_path: Path, summary_path: Path) -> dict:
    freeze = load_freeze()
    if tuple(freeze["development"]["seasons"]) != DEV_SEASONS:
        raise RuntimeError("PROP_V1_FIT_WINDOW_DRIFT")
    if int(freeze["validation"]["season"]) in DEV_SEASONS:
        raise RuntimeError("PROP_V1_FIT_2025_WINDOW_COLLISION")

    with tempfile.TemporaryDirectory(prefix="sportsedge-nfl-prop-v1-fit-") as tmp:
        runtime = _build_attempt9_runtime(Path(tmp))

        games_raw, games_receipt = _fetch(GAMES_URL)
        games = _csv_rows(games_raw)

        player_rows: list[dict[str, str]] = []
        receipts: dict[str, object] = {"games": games_receipt}
        for season in DEV_SEASONS:
            url = PLAYER_URL.format(season=season)
            raw, receipt = _fetch(url)
            rows = _csv_rows(raw)
            for row in rows:
                raw_season = str(row.get("season") or "").strip()
                if raw_season and int(float(raw_season)) != season:
                    raise RuntimeError(
                        f"PROP_V1_PLAYER_STATS_SEASON_MISMATCH:{season}:{raw_season}"
                    )
            player_rows.extend(rows)
            receipts[f"player_stats_{season}"] = receipt

        env = build_attempt9_team_environment(
            games, runtime, target_seasons=DEV_SEASONS
        )
        if not env:
            raise RuntimeError("PROP_V1_ATTEMPT9_TEAM_ENVIRONMENT_EMPTY")

        artifact = fit_prop_usage_v1(
            player_rows,
            env,
            source_receipts=receipts,
            attempt9_artifact_sha256=runtime["artifact_sha256"],
        )
        validate_artifact(artifact)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    summary = {
        "schema": "SPORTSEDGE_NFL_PROP_USAGE_V1_FIT_SUMMARY",
        "status": artifact["status"],
        "artifact_sha256": artifact["artifact_sha256"],
        "attempt9_artifact_sha256": artifact["attempt9_artifact_sha256"],
        "development_seasons": artifact["development_seasons"],
        "validation_season_accessed": False,
        "source_receipts": artifact["source_receipts"],
        "markets": {
            market: {
                "selected": row["selected"],
                "oof_n": row["oof_n"],
                "oof_residual_sigma_pooled": row["oof_residual_sigma_pooled"],
                "oof_residual_sigma_by_position": row["oof_residual_sigma_by_position"],
                "efficiency_prior_by_position": row["efficiency_prior_by_position"],
            }
            for market, row in artifact["markets"].items()
        },
        "authority": artifact["authority"],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("NFL_PROP_USAGE_V1_FIT=" + json.dumps(summary, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="artifacts/nfl_prop_usage_v1/nfl_prop_usage_v1_fit.json",
    )
    parser.add_argument(
        "--summary-out",
        default="artifacts/nfl_prop_usage_v1/nfl_prop_usage_v1_fit_summary.json",
    )
    args = parser.parse_args()
    run_fit(out_path=Path(args.out), summary_path=Path(args.summary_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
