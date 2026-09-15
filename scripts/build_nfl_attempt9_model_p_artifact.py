#!/usr/bin/env python3
"""Build the frozen probability wrapper for NFL attempt-9.

This script consumes the exact reconstructed attempt-9 runtime and the same
commit-pinned nflverse source used by that runtime.  It fits an isotonic mapping
on the 2017-2019 selection holdout only.  That fit is explicitly exposed and
has zero promotion authority; only later prospective 2026 evidence can validate
or promote this Model_P identity.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import erf, sqrt
from pathlib import Path
import re
from itertools import groupby
from typing import Any

import numpy as np

from scripts import build_nfl_attempt9_runtime_artifact as runtime_builder
from sportsedge.sports.nfl.attempt9_model_p import (
    CALIBRATION_CONTRACT,
    CANDIDATE_ID,
    MODEL_P_ID,
    MODEL_P_SCHEMA,
    MODEL_P_STATUS,
    canonical_sha256,
    fit_isotonic_blocks,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "config/public_training_sources_v1.json"
DEFAULT_RUNTIME = ROOT / "artifacts/football/nfl_attempt9_runtime_model.json"
DEFAULT_OUTPUT = ROOT / "artifacts/football/nfl_attempt9_model_p_v1.json"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_MAPPING_REQUIRED:{path}")
    return value


def _verify_runtime(artifact: dict[str, Any]) -> str:
    if artifact.get("schema_version") != "SPORTSEDGE_NFL_ATTEMPT9_RUNTIME_ARTIFACT_V1":
        raise ValueError("NFL_ATTEMPT9_RUNTIME_ARTIFACT_SCHEMA_INVALID")
    if artifact.get("status") != "RECONSTRUCTED_FROZEN_OWNER_RUNTIME_NOT_MODEL_P":
        raise ValueError("NFL_ATTEMPT9_RUNTIME_ARTIFACT_STATUS_INVALID")
    candidate = artifact.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("selected_attempt") != 9:
        raise ValueError("NFL_ATTEMPT9_RUNTIME_CANDIDATE_INVALID")
    authority = artifact.get("authority")
    if not isinstance(authority, dict) or authority.get("creates_model_p") is not False:
        raise ValueError("NFL_ATTEMPT9_RUNTIME_AUTHORITY_INVALID")
    expected = str(artifact.get("artifact_sha256") or "").lower()
    if len(expected) != 64:
        raise ValueError("NFL_ATTEMPT9_RUNTIME_ARTIFACT_SHA_MISSING")
    payload = dict(artifact)
    payload.pop("artifact_sha256", None)
    actual = canonical_sha256(payload)
    if actual != expected:
        raise ValueError(f"NFL_ATTEMPT9_RUNTIME_ARTIFACT_SHA_MISMATCH:{actual}:{expected}")
    return expected


def _predict(target: dict[str, Any], features: list[float]) -> float:
    vector = np.asarray(features, dtype=float)
    mean = np.asarray(target["feature_mean"], dtype=float)
    std = np.asarray(target["feature_std"], dtype=float)
    beta = np.asarray(target["coefficients"], dtype=float)
    if vector.shape != (6,) or mean.shape != (6,) or std.shape != (6,) or beta.shape != (6,):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_RUNTIME_GEOMETRY_INVALID")
    if np.any(std == 0):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_RUNTIME_ZERO_STD")
    return float(((vector - mean) / std) @ beta + float(target["intercept"]))


def _normal_upper(threshold: float, *, mean: float, sigma: float) -> float:
    if sigma <= 0.0:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_SIGMA_INVALID")
    cdf = 0.5 * (1.0 + erf((threshold - mean) / (sigma * sqrt(2.0))))
    return min(1.0 - 1e-9, max(1e-9, 1.0 - cdf))


def _holdout_rows(games: list[dict[str, Any]], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(games, key=lambda game: (game["date"], game["id"]))
    history: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
    targets = runtime["runtime"]["targets"]
    rows: list[dict[str, Any]] = []
    for game_date, group in groupby(ordered, key=lambda game: game["date"]):
        batch = list(group)
        for game in batch:
            home = game["home"]
            away = game["away"]
            if len(history[home]) < 5 or len(history[away]) < 5:
                continue
            hp = runtime_builder._weighted(history[home])
            ap = runtime_builder._weighted(history[away])
            features = [
                float(hp[0]), float(hp[1]), float(ap[0]), float(ap[1]),
                float(hp[0] - hp[1]), float(ap[0] - ap[1]),
            ]
            season = int(str(game_date)[:4])
            if 2017 <= season <= 2019:
                rows.append(
                    {
                        "game_id": game["id"],
                        "season": season,
                        "spread_line": game.get("spread_line"),
                        "total_line": game.get("total_line"),
                        "home_margin": float(game["hs"] - game["as"]),
                        "game_total": float(game["hs"] + game["as"]),
                        "predicted_margin": _predict(targets["margin"], features),
                        "predicted_total": _predict(targets["total"], features),
                    }
                )
        for game in batch:
            history[game["home"]].append((game["hs"], game["as"]))
            history[game["away"]].append((game["as"], game["hs"]))
    return rows


def _market_fit(rows: list[dict[str, Any]], *, market: str, sigma: float) -> dict[str, Any]:
    scores: list[float] = []
    outcomes: list[int] = []
    pushes = 0
    for row in rows:
        if market == "spread":
            line = row.get("spread_line")
            actual = float(row["home_margin"])
            prediction = float(row["predicted_margin"])
        else:
            line = row.get("total_line")
            actual = float(row["game_total"])
            prediction = float(row["predicted_total"])
        if line is None:
            continue
        threshold = float(line)
        if actual == threshold:
            pushes += 1
            continue
        scores.append(_normal_upper(threshold, mean=prediction, sigma=sigma))
        outcomes.append(int(actual > threshold))
    if len(scores) < 200:
        raise ValueError(f"NFL_ATTEMPT9_MODEL_P_CALIBRATION_UNDERPOWERED:{market}:{len(scores)}")
    blocks = fit_isotonic_blocks(scores, outcomes)
    return {
        "sigma": float(sigma),
        "sigma_source": "FROZEN_ATTEMPT9_2017_2019_HOLDOUT_RMSE_SELECTION_EXPOSED",
        "fit_n": len(scores),
        "pushes_excluded": pushes,
        "calibration_blocks": blocks,
        "calibration_block_count": len(blocks),
        "fit_role": "SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE",
        "promotion_authority": False,
    }


def build_model_p_artifact(
    *,
    runtime: dict[str, Any],
    source_config: dict[str, Any],
    code_git_sha: str,
) -> dict[str, Any]:
    code_sha = str(code_git_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(code_sha):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_CODE_GIT_SHA_INVALID")
    runtime_sha = _verify_runtime(runtime)
    source = source_config["sources"]["nfl_attempt9"]
    raw = runtime_builder._fetch(source["raw_url"])
    observed_source_sha = sha256(raw).hexdigest()
    if observed_source_sha != source["expected_sha256"]:
        raise ValueError(
            f"NFL_ATTEMPT9_MODEL_P_SOURCE_SHA_MISMATCH:{observed_source_sha}:{source['expected_sha256']}"
        )
    if observed_source_sha != runtime["source"]["sha256"]:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_RUNTIME_SOURCE_BINDING_MISMATCH")

    games = runtime_builder.parse_games(raw)
    rows = _holdout_rows(games, runtime)
    margin_predictions = np.asarray([row["predicted_margin"] for row in rows], dtype=float)
    total_predictions = np.asarray([row["predicted_total"] for row in rows], dtype=float)
    if len(rows) != int(runtime["runtime"]["targets"]["margin"]["holdout_count"]):
        raise ValueError(f"NFL_ATTEMPT9_MODEL_P_HOLDOUT_COUNT_MISMATCH:{len(rows)}")
    for market, predictions in (("margin", margin_predictions), ("total", total_predictions)):
        expected = runtime["runtime"]["targets"][market]["holdout_prediction_sha256"]
        actual = runtime_builder._prediction_sha(predictions)
        if actual != expected:
            raise ValueError(
                f"NFL_ATTEMPT9_MODEL_P_PREDICTION_BINDING_MISMATCH:{market}:{actual}:{expected}"
            )

    markets = {
        "spread": _market_fit(
            rows,
            market="spread",
            sigma=float(runtime["runtime"]["targets"]["margin"]["holdout_rmse"]),
        ),
        "total": _market_fit(
            rows,
            market="total",
            sigma=float(runtime["runtime"]["targets"]["total"]["holdout_rmse"]),
        ),
    }
    artifact: dict[str, Any] = {
        "schema_version": MODEL_P_SCHEMA,
        "status": MODEL_P_STATUS,
        "model_p_id": MODEL_P_ID,
        "candidate_id": CANDIDATE_ID,
        "code_git_sha": code_sha,
        "runtime_artifact_sha256": runtime_sha,
        "source_sha256": observed_source_sha,
        "candidate": {
            "selected_attempt": 9,
            "feature_set": "exponential_recency_weighted_baseline",
            "decay": 0.85,
        },
        "calibration_fit": {
            "contract": CALIBRATION_CONTRACT,
            "seasons": [2017, 2018, 2019],
            "role": "SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE",
            "raw_prediction_identity_verified": True,
            "raw_holdout_count": len(rows),
            "source": "PINNED_NFLVERSE_SOURCE_BOUND_TO_ATTEMPT9_RUNTIME",
            "note": "This fit defines Model_P mechanics only. It cannot attest calibration, promotion, deployment, CLV, ROI, Truth Gate, OFFICIAL, or staking.",
        },
        "markets": markets,
        "line_contract": {
            "spread": "HOME_HANDICAP_ADDED_TO_HOME_MARGIN; integer line blocked until push mass is validated",
            "total": "OVER_IF_GAME_TOTAL_GT_LINE; integer line blocked until push mass is validated",
            "moneyline": "UNSUPPORTED_V1_NO_TIE_MASS_MODEL",
        },
        "prospective_evidence": {
            "season": 2026,
            "owner": "ATTEMPT9_ONLY",
            "historical_fit_counts_as_promotion_evidence": False,
            "activation_rule": "ONLY_MODEL_P_ROWS_CREATED_AFTER_THIS_EXACT_CODE_AND_ARTIFACT_IDENTITY_IS_FROZEN_MAY_ENTER_FORWARD_EVIDENCE",
            "inherited_m2_evidence_allowed": False,
            "backfill_allowed": False,
        },
        "authority": {
            "creates_model_p": True,
            "historical_fit_promotion_authority": False,
            "deployed": False,
            "truth_gate_pass": False,
            "official_authority": False,
            "staking_authority": False,
        },
    }
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--source-config", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--code-git-sha", required=True)
    args = parser.parse_args()
    artifact = build_model_p_artifact(
        runtime=_read_json(args.runtime),
        source_config=_read_json(args.source_config),
        code_git_sha=args.code_git_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": artifact["status"],
        "model_p_id": artifact["model_p_id"],
        "artifact_sha256": artifact["artifact_sha256"],
        "spread_fit_n": artifact["markets"]["spread"]["fit_n"],
        "total_fit_n": artifact["markets"]["total"]["fit_n"],
        "creates_model_p": True,
        "promotion_authority": False,
        "deployed": False,
        "official_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
