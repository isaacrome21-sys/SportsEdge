#!/usr/bin/env python3
"""Reconstruct the frozen NFL attempt-9 owner as a deterministic runtime artifact.

This does not promote the candidate or create Model_P. It rebuilds the exact
pre-2026 selected research owner from its pinned public source so prospective
raw margin/total forecasts can execute without refitting against 2026 data.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import platform
from collections import defaultdict
from itertools import groupby
from pathlib import Path
import sys
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "config/public_training_sources_v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/football/nfl_attempt9_runtime_model.json"
FEATURE_NAMES = [
    "home_points_for",
    "home_points_against",
    "away_points_for",
    "away_points_against",
    "home_net",
    "away_net",
]
DECAY = 0.85
HOLDOUT_START = 2017
HOLDOUT_END = 2019
TARGETS = {"margin": 10.0, "total": 0.1}
THREAD_ENV_KEYS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
EXPECTED_COEFFICIENTS = {
    "margin": [
        1.9219959071859163,
        -1.1939546971867534,
        -1.700049235015833,
        0.4894639011852299,
        2.051162351492163,
        -1.4712827317889383,
    ],
    "total": [
        1.9674873702327231,
        1.4677035717536322,
        1.6205830069927165,
        1.2581489139175235,
        0.45966409421453325,
        0.3368500740711741,
    ],
}
EXPECTED_HOLDOUT_RMSE = {
    "margin": 13.78774897397055,
    "total": 13.99738332096112,
}
EXPECTED_HOLDOUT_COUNT = 779


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _float_list_json(values: list[float] | np.ndarray) -> str:
    return json.dumps([float(value) for value in values], separators=(",", ":"))


def _prediction_sha(values: np.ndarray) -> str:
    return _sha256(_float_list_json(values).encode("utf-8"))


def _numpy_config_snapshot() -> dict:
    """Return the current NumPy/BLAS build metadata without guessing history."""
    try:
        value = np.show_config(mode="dicts")
        if isinstance(value, dict):
            return value
    except (TypeError, ValueError):
        pass
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        np.show_config()
    text = buffer.getvalue()
    return {
        "fallback_text": text,
        "fallback_text_sha256": _sha256(text.encode("utf-8")),
    }


def _numeric_environment() -> dict:
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "thread_environment": {key: os.environ.get(key) for key in THREAD_ENV_KEYS},
        "numpy_config": _numpy_config_snapshot(),
    }


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "SportsEdge-attempt9-runtime/1.0"})
    with urlopen(req, timeout=120) as response:
        return response.read()


def _optional_float(row: dict[str, str], key: str) -> float | None:
    raw = row.get(key)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_games(raw: bytes) -> list[dict]:
    games: list[dict] = []
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        try:
            season = int(row["season"])
            home_score = int(float(row["home_score"]))
            away_score = int(float(row["away_score"]))
        except (KeyError, TypeError, ValueError):
            continue
        if season not in set(range(2010, 2020)):
            continue
        if row.get("game_type", "REG") not in ("REG", "POST"):
            continue
        games.append(
            {
                "date": row.get("gameday") or f"{season}-01-01",
                "id": row.get("game_id", ""),
                "home": row["home_team"],
                "away": row["away_team"],
                "hs": home_score,
                "as": away_score,
                "spread_line": _optional_float(row, "spread_line"),
                "total_line": _optional_float(row, "total_line"),
            }
        )
    return games


def _weighted(values: list[tuple[int, int]]) -> np.ndarray:
    array = np.asarray(values[-10:], dtype=float)
    weights = DECAY ** np.arange(len(array) - 1, -1, -1)
    return np.average(array, axis=0, weights=weights)


def build_features(games: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    ordered = sorted(games, key=lambda game: (game["date"], game["id"]))
    history: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
    x_rows: list[list[float]] = []
    margins: list[float] = []
    totals: list[float] = []
    dates: list[str] = []
    for game_date, group in groupby(ordered, key=lambda game: game["date"]):
        batch = list(group)
        for game in batch:
            home = game["home"]
            away = game["away"]
            if len(history[home]) < 5 or len(history[away]) < 5:
                continue
            hp = _weighted(history[home])
            ap = _weighted(history[away])
            x_rows.append(
                [hp[0], hp[1], ap[0], ap[1], hp[0] - hp[1], ap[0] - ap[1]]
            )
            margins.append(float(game["hs"] - game["as"]))
            totals.append(float(game["hs"] + game["as"]))
            dates.append(game_date)
        for game in batch:
            history[game["home"]].append((game["hs"], game["as"]))
            history[game["away"]].append((game["as"], game["hs"]))
    return (
        np.asarray(x_rows, dtype=float),
        np.asarray(margins, dtype=float),
        np.asarray(totals, dtype=float),
        dates,
    )


def fit_target(x: np.ndarray, y: np.ndarray, dates: list[str], alpha: float) -> dict:
    holdout = np.asarray(
        [HOLDOUT_START <= int(date[:4]) <= HOLDOUT_END for date in dates], dtype=bool
    )
    x_train = x[~holdout]
    y_train = y[~holdout]
    x_holdout = x[holdout]
    y_holdout = y[holdout]
    if len(x_train) < 100 or len(x_holdout) != EXPECTED_HOLDOUT_COUNT:
        raise RuntimeError(
            f"ATTEMPT9_SPLIT_MISMATCH:train={len(x_train)}:holdout={len(x_holdout)}"
        )

    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std == 0] = 1.0
    scaled_train = (x_train - mean) / std
    scaled_holdout = (x_holdout - mean) / std

    centered_x = scaled_train - scaled_train.mean(axis=0)
    centered_y = y_train - y_train.mean()
    beta = np.linalg.solve(
        centered_x.T @ centered_x + float(alpha) * np.eye(scaled_train.shape[1]),
        centered_x.T @ centered_y,
    )
    intercept = float(y_train.mean() - scaled_train.mean(axis=0) @ beta)
    predictions = scaled_holdout @ beta + intercept
    rmse = float(np.sqrt(np.mean((predictions - y_holdout) ** 2)))
    coefficient_json = _float_list_json(beta)
    prediction_sha = _prediction_sha(predictions)
    return {
        "alpha": float(alpha),
        "feature_mean": [float(value) for value in mean],
        "feature_std": [float(value) for value in std],
        "coefficients": [float(value) for value in beta],
        "coefficient_json": coefficient_json,
        "coefficient_json_sha256": _sha256(coefficient_json.encode("utf-8")),
        "intercept": intercept,
        "holdout_count": int(len(predictions)),
        "holdout_rmse": rmse,
        "holdout_prediction_sha256": prediction_sha,
    }


def reconstruct(source_config: Path) -> dict:
    config = json.loads(source_config.read_text(encoding="utf-8"))
    source = config["sources"]["nfl_attempt9"]
    historical_environment = source.get("historical_numeric_environment")
    if not isinstance(historical_environment, dict):
        raise RuntimeError("NFL_ATTEMPT9_HISTORICAL_NUMERIC_ENVIRONMENT_MISSING")
    if np.__version__ != historical_environment.get("numpy_version"):
        raise RuntimeError(
            "NFL_ATTEMPT9_NUMPY_VERSION_MISMATCH:"
            f"{np.__version__}:{historical_environment.get('numpy_version')}"
        )

    raw = _fetch(source["raw_url"])
    observed_source_sha = _sha256(raw)
    if observed_source_sha != source["expected_sha256"]:
        raise RuntimeError(
            f"NFL_ATTEMPT9_SOURCE_SHA_MISMATCH:{observed_source_sha}:{source['expected_sha256']}"
        )

    games = parse_games(raw)
    x, margin, total, dates = build_features(games)
    if len(games) != 2560 or len(x) != 2467:
        raise RuntimeError(f"NFL_ATTEMPT9_ROWCOUNT_MISMATCH:{len(games)}:{len(x)}")

    targets = {
        "margin": fit_target(x, margin, dates, TARGETS["margin"]),
        "total": fit_target(x, total, dates, TARGETS["total"]),
    }
    expected_prediction_sha = source["holdout_prediction_sha256"]
    for name, target in targets.items():
        expected_coefficient_json = _float_list_json(EXPECTED_COEFFICIENTS[name])
        actual_coefficient_json = str(target["coefficient_json"])
        if actual_coefficient_json != expected_coefficient_json:
            raise RuntimeError(
                "NFL_ATTEMPT9_COEFFICIENT_TEXT_MISMATCH:"
                f"{name}:actual={actual_coefficient_json}:expected={expected_coefficient_json}"
            )
        if not np.isclose(
            target["holdout_rmse"], EXPECTED_HOLDOUT_RMSE[name], rtol=0.0, atol=1e-12
        ):
            raise RuntimeError(
                "NFL_ATTEMPT9_RMSE_MISMATCH:"
                f"{name}:actual={target['holdout_rmse']}:expected={EXPECTED_HOLDOUT_RMSE[name]}"
            )
        if target["holdout_prediction_sha256"] != expected_prediction_sha[name]:
            raise RuntimeError(
                "NFL_ATTEMPT9_PREDICTION_SHA_MISMATCH_WITH_EXACT_COEFFICIENTS:"
                f"{name}:actual={target['holdout_prediction_sha256']}:"
                f"expected={expected_prediction_sha[name]}"
            )

    artifact = {
        "schema_version": "SPORTSEDGE_NFL_ATTEMPT9_RUNTIME_ARTIFACT_V1",
        "status": "RECONSTRUCTED_FROZEN_OWNER_RUNTIME_NOT_MODEL_P",
        "candidate": {
            "selected_attempt": 9,
            "feature_set": "exponential_recency_weighted_baseline",
            "decay": DECAY,
            "training_seasons": [2010, 2016],
            "historical_holdout_seasons": [2017, 2019],
            "feature_names": FEATURE_NAMES,
        },
        "source": {
            "repository": source["repository"],
            "commit": source["commit"],
            "path": source["path"],
            "sha256": observed_source_sha,
        },
        "frozen_selection_provenance": {
            "derivation_commit": source["derivation_commit"],
            "actions_run_id": source["actions_run_id"],
            "actions_artifact_id": source["actions_artifact_id"],
            "actions_artifact_digest": source["actions_artifact_digest"],
            "report_content_sha256": source["report_content_sha256"],
        },
        "runtime": {
            "historical_numeric_environment": historical_environment,
            "reconstruction_numeric_environment": _numeric_environment(),
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
        "use": "PROSPECTIVE_RAW_MARGIN_AND_TOTAL_FORECASTS_ONLY_UNTIL_SEPARATE_PROBABILITY_AND_PROMOTION_CONTRACT_EARNS_AUTHORITY",
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    artifact["artifact_sha256"] = _sha256(canonical)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-config", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(
        json.dumps(
            {"nfl_attempt9_reconstruction_numeric_environment": _numeric_environment()},
            sort_keys=True,
            default=str,
        ),
        flush=True,
    )
    artifact = reconstruct(args.source_config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": artifact["status"],
        "artifact_sha256": artifact["artifact_sha256"],
        "source_sha256": artifact["source"]["sha256"],
        "model_p_created": False,
        "promotion_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())