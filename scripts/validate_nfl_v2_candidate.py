#!/usr/bin/env python3
"""Compare the isolated NFL V2 candidate against the frozen key-number tolerance.

This is diagnostic evidence only. It intentionally does not emit the canonical
production math attestation contract and cannot promote or deploy the candidate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.m2_v2_candidate import (
    NFL_M2_V2_CANDIDATE_MODEL_ID,
    NFL_M2_V2_DISTRIBUTION_CONTRACT,
)
from sportsedge.sports.nfl.simulator_profile import (
    build_nfl_simulator_profile,
    validate_profile_fit,
)

_KEY_PROFILE_CONTRACT = "NFL_M2_V2_CANDIDATE_OOS_SIGNED_KEY_PMF_V1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("candidate_evidence", type=Path)
    parser.add_argument("--max-abs-error", type=float, default=0.005)
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_m2_v2_candidate_key_math.json"))
    args = parser.parse_args()

    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    evidence = json.loads(args.candidate_evidence.read_text(encoding="utf-8"))
    if evidence.get("status") != "DIAGNOSTIC_CANDIDATE_ONLY" or evidence.get("promotion_eligible") is not False:
        raise SystemExit("NFL_M2_V2_DIAGNOSTIC_STATUS_REQUIRED")
    if evidence.get("model_id") != NFL_M2_V2_CANDIDATE_MODEL_ID:
        raise SystemExit("NFL_M2_V2_MODEL_ID_MISMATCH")
    if evidence.get("distribution_contract") != NFL_M2_V2_DISTRIBUTION_CONTRACT:
        raise SystemExit("NFL_M2_V2_DISTRIBUTION_CONTRACT_MISMATCH")
    profile_payload = evidence.get("candidate_distribution_profile")
    if not isinstance(profile_payload, dict):
        raise SystemExit("NFL_M2_V2_CANDIDATE_PROFILE_REQUIRED")
    if profile_payload.get("contract") != _KEY_PROFILE_CONTRACT:
        raise SystemExit("NFL_M2_V2_CANDIDATE_PROFILE_CONTRACT_INVALID")
    if profile_payload.get("model_id") != NFL_M2_V2_CANDIDATE_MODEL_ID:
        raise SystemExit("NFL_M2_V2_CANDIDATE_PROFILE_IDENTITY_MISMATCH")
    raw_pmf = profile_payload.get("signed_key_probability")
    if not isinstance(raw_pmf, dict):
        raise SystemExit("NFL_M2_V2_CANDIDATE_PMF_REQUIRED")

    profile = build_nfl_simulator_profile(audit, version="nfl-m2-v2-candidate-oos-key-emergent-v1")
    key_numbers = tuple(sorted(int(key) for key in profile["validation_target_key_frequency"]))
    try:
        candidate_pmf = {key: float(raw_pmf[str(key)]) for key in key_numbers}
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("NFL_M2_V2_CANDIDATE_PMF_INVALID") from exc
    if any(value < 0.0 or value > 1.0 for value in candidate_pmf.values()):
        raise SystemExit("NFL_M2_V2_CANDIDATE_PMF_INVALID")

    fit = validate_profile_fit(profile, candidate_pmf, max_abs_error=args.max_abs_error)
    payload = {
        "schema_version": 1,
        "status": "DIAGNOSTIC_CANDIDATE_ONLY",
        "promotion_eligible": False,
        "model_id": NFL_M2_V2_CANDIDATE_MODEL_ID,
        "distribution_contract": NFL_M2_V2_DISTRIBUTION_CONTRACT,
        "historical_profile_version": profile["version"],
        "key_number_contract": profile["key_number_contract"],
        "max_abs_error": float(args.max_abs_error),
        "fit": fit,
        "heldout_game_count": int(profile_payload.get("heldout_game_count", 0)),
        "test_seasons": list(profile_payload.get("test_seasons") or []),
        "production_registry_consumes_this_artifact": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
