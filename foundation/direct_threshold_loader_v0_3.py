#!/usr/bin/env python3
"""Exact-artifact loader for SportsEdge direct-threshold markets.

This is the runtime-side bridge for registry v1.6 artifact parity. It does not
create Model_P by itself; it only proves that the exact serialized artifact
required by the registry was loaded and structurally matches the declared
market, code version, features, thresholds, and validation hash.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import joblib

REQUIRED = {
    "rbi": {
        "path": "sportsedge_rbi_direct_v1.joblib",
        "artifact_hash": "d77779e682bebf7c47a41829f1db240b7137eef4acd2baa553b346a28bff8375",
        "validation_hash": "0debe7836f983e2711a347ba76be3ce1ca5c36a5b76421d36575b84bbbc8463b",
        "code_version": "direct_threshold_v1.0",
        "features": ["hr_rate", "ob_rate", "xb_rate", "team_obp", "slot"],
        "thresholds": [0.5, 1.5, 2.5],
    },
    "runs": {
        "path": "sportsedge_runs_direct_v1.joblib",
        "artifact_hash": "a999b298576ad0198db142621817578724428b78badafdbbb631c19f2f2d7a07",
        "validation_hash": "25a83e319ba6682cb1c60d9c4e5d9f758feffc3f3bc19a16ca0fb21deb2d03bf",
        "code_version": "direct_threshold_v1.0",
        "features": ["hr_rate", "ob_rate", "xb_rate", "team_obp", "slot"],
        "thresholds": [0.5, 1.5, 2.5],
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_direct_threshold_artifact(runtime_root: Path, market: str) -> Dict[str, Any]:
    req = REQUIRED.get(market)
    if req is None:
        raise ValueError(f"unsupported direct-threshold market: {market}")
    path = runtime_root / req["path"]
    if not path.is_file():
        raise RuntimeError(f"MISSING_REQUIRED_ARTIFACT:{market}:{path}")
    actual_hash = sha256_file(path)
    if actual_hash != req["artifact_hash"]:
        raise RuntimeError(f"ARTIFACT_HASH_MISMATCH:{market}:{actual_hash}")

    obj = joblib.load(path)
    if not isinstance(obj, dict):
        raise RuntimeError(f"ARTIFACT_STRUCTURE_INVALID:{market}:not_dict")
    checks = {
        "market": obj.get("market") == market,
        "code_version": obj.get("code_version") == req["code_version"],
        "features": obj.get("features") == req["features"],
        "thresholds": obj.get("thresholds") == req["thresholds"],
        "validation_hash": obj.get("validation_hash") == req["validation_hash"],
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise RuntimeError(f"ARTIFACT_METADATA_MISMATCH:{market}:{','.join(bad)}")

    models = obj.get("models")
    expected_keys = {
        f"{season}|{threshold}"
        for season in (2023, 2024)
        for threshold in req["thresholds"]
    }
    if not isinstance(models, dict) or set(models) != expected_keys:
        raise RuntimeError(f"ARTIFACT_MODEL_KEYS_INVALID:{market}")
    for key, model in models.items():
        if not hasattr(model, "predict_proba"):
            raise RuntimeError(f"ARTIFACT_MODEL_INVALID:{market}:{key}")

    return {
        "market": market,
        "path": str(path),
        "artifact_hash": actual_hash,
        "validation_hash": obj["validation_hash"],
        "code_version": obj["code_version"],
        "features": list(obj["features"]),
        "thresholds": list(obj["thresholds"]),
        "loaded": True,
        "artifact": obj,
    }


def load_all_direct_threshold_artifacts(runtime_root: Path) -> Dict[str, Any]:
    loaded = {m: load_direct_threshold_artifact(runtime_root, m) for m in REQUIRED}
    return {
        "loaded": loaded,
        "capability_attestation": {
            "loaded_artifacts": {m: rec["artifact_hash"] for m, rec in loaded.items()},
            "verified_requirements": [
                "runtime MUST load sportsedge_rbi_direct_v1.joblib with the recorded artifact_hash; any substitution reverts this market to VALIDATED_NOT_DEPLOYED",
                "runtime MUST load sportsedge_runs_direct_v1.joblib with the recorded artifact_hash; any substitution reverts this market to VALIDATED_NOT_DEPLOYED",
            ],
        },
    }
