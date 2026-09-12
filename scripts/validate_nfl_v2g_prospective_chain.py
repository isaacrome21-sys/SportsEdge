#!/usr/bin/env python3
"""Validate byte/provenance integrity across the NFL V2G prospective chain."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.sports.nfl.m2_v2g_forward import validate_prospective_prediction

PAPER_SCHEMA = "SPORTSEDGE_NFL_V2G_PAPER_DECISION_V1"
BINDING_SCHEMA = "SPORTSEDGE_NFL_V2G_MARKET_EVIDENCE_BINDING_V1"
POLICY_SCHEMA = "SPORTSEDGE_NFL_V2G_PROSPECTIVE_PAPER_EVALUATION_POLICY_V1"


def die(code: str) -> None:
    raise SystemExit(code)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(payload: dict[str, Any], hash_field: str) -> str:
    value = dict(payload)
    value.pop(hash_field, None)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        die(f"NFL_V2G_CHAIN_JSON_OBJECT_REQUIRED:{path}")
    return value


def validate(prediction: Path, paper_path: Path, policy_path: Path, opener: Path | None = None, binding_path: Path | None = None) -> dict[str, Any]:
    pred = load(prediction)
    paper = load(paper_path)
    policy = load(policy_path)
    if policy.get("schema_version") != POLICY_SCHEMA:
        die("NFL_V2G_CHAIN_POLICY_SCHEMA_INVALID")
    validate_prospective_prediction(pred)
    if paper.get("schema_version") != PAPER_SCHEMA:
        die("NFL_V2G_CHAIN_PAPER_SCHEMA_INVALID")
    if paper.get("game_id") != pred.get("game_id") or paper.get("candidate_id") != pred.get("candidate_id"):
        die("NFL_V2G_CHAIN_PAPER_IDENTITY_MISMATCH")
    if paper.get("artifact_sha256") != pred.get("artifact_sha256"):
        die("NFL_V2G_CHAIN_PAPER_ARTIFACT_MISMATCH")
    if paper.get("prediction_sha256") != pred.get("prediction_sha256"):
        die("NFL_V2G_CHAIN_PAPER_PREDICTION_MISMATCH")
    if paper.get("prediction_file_sha256") != sha256_file(prediction):
        die("NFL_V2G_CHAIN_PREDICTION_FILE_SHA_MISMATCH")
    if paper.get("policy_file_sha256") != sha256_file(policy_path):
        die("NFL_V2G_CHAIN_POLICY_FILE_SHA_MISMATCH")
    expected_paper_sha = canonical_sha(paper, "paper_decision_sha256")
    if paper.get("paper_decision_sha256") != expected_paper_sha:
        die("NFL_V2G_CHAIN_PAPER_DECISION_SHA_MISMATCH")
    if paper.get("market_prices_consumed_by_model") is not False:
        die("NFL_V2G_CHAIN_MARKET_LEAKAGE")
    for key in ("staking_allowed", "promotion_authority", "may_create_model_p", "market_eligibility_changed", "official_status_granted"):
        if paper.get(key) is not False:
            die(f"NFL_V2G_CHAIN_PAPER_AUTHORITY_INVALID:{key}")

    if opener is not None:
        if paper.get("opener_capture_file_sha256") != sha256_file(opener):
            die("NFL_V2G_CHAIN_OPENER_FILE_SHA_MISMATCH")

    binding = None
    if binding_path is not None and binding_path.exists():
        binding = load(binding_path)
        if binding.get("schema_version") != BINDING_SCHEMA:
            die("NFL_V2G_CHAIN_BINDING_SCHEMA_INVALID")
        if binding.get("game_id") != pred.get("game_id") or binding.get("candidate_id") != pred.get("candidate_id"):
            die("NFL_V2G_CHAIN_BINDING_IDENTITY_MISMATCH")
        bound_pred = binding.get("prediction") or {}
        if bound_pred.get("prediction_sha256") != pred.get("prediction_sha256"):
            die("NFL_V2G_CHAIN_BINDING_PREDICTION_SHA_MISMATCH")
        if bound_pred.get("file_sha256") != sha256_file(prediction):
            die("NFL_V2G_CHAIN_BINDING_PREDICTION_FILE_SHA_MISMATCH")
        if binding.get("market_prices_consumed_by_model") is not False:
            die("NFL_V2G_CHAIN_BINDING_MARKET_LEAKAGE")
        for key in ("promotion_authority", "may_create_model_p", "market_eligibility_changed", "official_status_granted"):
            if binding.get(key) is not False:
                die(f"NFL_V2G_CHAIN_BINDING_AUTHORITY_INVALID:{key}")

    return {
        "status": "NFL_V2G_PROSPECTIVE_CHAIN_VALID",
        "game_id": pred.get("game_id"),
        "prediction_sha256": pred.get("prediction_sha256"),
        "paper_decision_sha256": paper.get("paper_decision_sha256"),
        "binding_present": binding is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--paper-decision", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--opener", type=Path)
    parser.add_argument("--market-binding", type=Path)
    args = parser.parse_args()
    result = validate(args.prediction, args.paper_decision, args.policy, args.opener, args.market_binding)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
