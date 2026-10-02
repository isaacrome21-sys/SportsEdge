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
import sys
import tempfile

import numpy as np

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
from scripts import build_nfl_attempt9_runtime_artifact as attempt9_runtime

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
    """Materialize frozen Attempt-9 without re-solving its ridge coefficients.

    The original selected coefficients and holdout prediction hashes are frozen
    in build_nfl_attempt9_runtime_artifact.py / public_training_sources_v1.json.
    Re-solving the same ridge system can differ in the last ULP across hosted
    runner CPU/SIMD surfaces. This adapter instead injects the exact frozen
    coefficients and still requires the original holdout prediction SHA256 and
    RMSE to reproduce exactly before the prop fit may proceed.
    """
    source_config = ROOT / "config" / "public_training_sources_v1.json"
    config = json.loads(source_config.read_text())
    source = config["sources"]["nfl_attempt9"]

    raw, source_receipt = _fetch(source["raw_url"])
    if source_receipt["sha256"] != source["expected_sha256"]:
        raise RuntimeError(
            "PROP_V1_ATTEMPT9_SOURCE_SHA_MISMATCH:"
            f"{source_receipt['sha256']}:{source['expected_sha256']}"
        )

    games = attempt9_runtime.parse_games(raw)
    x, margin, total, dates = attempt9_runtime.build_features(games)
    if len(games) != 2560 or len(x) != 2467:
        raise RuntimeError(
            f"PROP_V1_ATTEMPT9_ROWCOUNT_MISMATCH:{len(games)}:{len(x)}"
        )

    holdout = np.asarray(
        [
            attempt9_runtime.HOLDOUT_START <= int(date[:4]) <= attempt9_runtime.HOLDOUT_END
            for date in dates
        ],
        dtype=bool,
    )
    if int(holdout.sum()) != attempt9_runtime.EXPECTED_HOLDOUT_COUNT:
        raise RuntimeError(
            f"PROP_V1_ATTEMPT9_HOLDOUT_COUNT_MISMATCH:{int(holdout.sum())}"
        )

    targets: dict[str, object] = {}
    for name, y in (("margin", margin), ("total", total)):
        x_train = x[~holdout]
        y_train = y[~holdout]
        x_holdout = x[holdout]
        y_holdout = y[holdout]

        mean = x_train.mean(axis=0)
        std = x_train.std(axis=0)
        std[std == 0] = 1.0
        scaled_train = (x_train - mean) / std
        scaled_holdout = (x_holdout - mean) / std

        beta = np.asarray(attempt9_runtime.EXPECTED_COEFFICIENTS[name], dtype=float)
        intercept = float(
            y_train.mean() - scaled_train.mean(axis=0) @ beta
        )
        predictions = scaled_holdout @ beta + intercept
        prediction_sha = attempt9_runtime._prediction_sha(predictions)
        expected_prediction_sha = source["holdout_prediction_sha256"][name]
        if prediction_sha != expected_prediction_sha:
            raise RuntimeError(
                "PROP_V1_ATTEMPT9_FIXED_BETA_PREDICTION_SHA_MISMATCH:"
                f"{name}:actual={prediction_sha}:expected={expected_prediction_sha}"
            )

        rmse = float(np.sqrt(np.mean((predictions - y_holdout) ** 2)))
        expected_rmse = attempt9_runtime.EXPECTED_HOLDOUT_RMSE[name]
        if not np.isclose(rmse, expected_rmse, rtol=0.0, atol=0.0):
            raise RuntimeError(
                "PROP_V1_ATTEMPT9_FIXED_BETA_RMSE_MISMATCH:"
                f"{name}:actual={rmse}:expected={expected_rmse}"
            )

        targets[name] = {
            "alpha": float(attempt9_runtime.TARGETS[name]),
            "feature_mean": [float(value) for value in mean],
            "feature_std": [float(value) for value in std],
            "coefficients": [float(value) for value in beta],
            "coefficient_json": attempt9_runtime._float_list_json(beta),
            "intercept": intercept,
            "holdout_count": int(len(predictions)),
            "holdout_rmse": rmse,
            "holdout_prediction_sha256": prediction_sha,
        }

    artifact = {
        "schema_version": "SPORTSEDGE_NFL_ATTEMPT9_RUNTIME_ARTIFACT_V1",
        "status": "RECONSTRUCTED_FROZEN_OWNER_RUNTIME_NOT_MODEL_P",
        "candidate": {
            "selected_attempt": 9,
            "feature_set": "exponential_recency_weighted_baseline",
            "decay": attempt9_runtime.DECAY,
            "training_seasons": [2010, 2016],
            "historical_holdout_seasons": [2017, 2019],
            "feature_names": attempt9_runtime.FEATURE_NAMES,
        },
        "source": {
            "repository": source["repository"],
            "commit": source["commit"],
            "path": source["path"],
            "sha256": source_receipt["sha256"],
        },
        "frozen_selection_provenance": {
            "derivation_commit": source["derivation_commit"],
            "actions_run_id": source["actions_run_id"],
            "actions_artifact_id": source["actions_artifact_id"],
            "actions_artifact_digest": source["actions_artifact_digest"],
            "report_content_sha256": source["report_content_sha256"],
        },
        "runtime": {
            "historical_numeric_environment": source["historical_numeric_environment"],
            "reconstruction_method": "FROZEN_EXACT_COEFFICIENTS_NO_RIDGE_RESOLVE",
            "targets": targets,
        },
        "authority": {
            "creates_model_p": False,
            "promotion_authority": False,
            "truth_gate_pass": False,
            "official_authority": False,
            "staking_authority": False,
            "market_prices_used_as_features": False,
        },
        "use": (
            "PROP_V1_DEVELOPMENT_TEAM_SCORING_ENVIRONMENT_ONLY;"
            "2025_VALIDATION_UNTOUCHED"
        ),
    }
    canonical = json.dumps(
        artifact, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    artifact["artifact_sha256"] = sha256(canonical).hexdigest()

    output = temp_dir / "attempt9.json"
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
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
