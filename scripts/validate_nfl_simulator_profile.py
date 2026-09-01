#!/usr/bin/env python3
"""Build a hash-bound NFL key-number math artifact from real history.

Historical signed key frequencies are validation targets only. They are not fed
back into the simulator. By default the script always exits successfully after
producing evidence; pass ``--require-pass`` when a promotion job should fail if
the math gate itself is still blocked.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.core.simulate.football import KeyNumberMarginModel
from sportsedge.core.validation.math_attestation import attest_validated_math
from sportsedge.sports.nfl.simulator_profile import (
    build_math_attestation_artifact,
    build_nfl_simulator_profile,
    validate_profile_fit,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("--version", default="nfl-key-emergent-v3")
    parser.add_argument("--mean", type=float, default=0.0)
    parser.add_argument("--sigma", type=float, default=13.5)
    parser.add_argument("--max-abs-error", type=float, default=0.005)
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--production-evidence", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/nfl_simulator_profile.json"))
    args = parser.parse_args()

    audit = json.loads(args.audit_json.read_text())
    profile = build_nfl_simulator_profile(audit, version=args.version)

    key_numbers = tuple(sorted(int(key) for key in profile["validation_target_key_frequency"]))
    production_identity = None
    if args.production_evidence is not None:
        evidence = json.loads(args.production_evidence.read_text(encoding="utf-8"))
        if evidence.get("model_id") != "nfl_m2_ridge_v1":
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_MODEL_ID_MISMATCH")
        if evidence.get("feature_contract") != "NFL_M2_V1_MARKET_BLIND":
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_FEATURE_CONTRACT_MISMATCH")
        production = evidence.get("production_distribution_profile")
        if not isinstance(production, dict):
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_REQUIRED")
        if production.get("contract") != "NFL_M2_OOS_EMERGENT_SIGNED_KEY_PMF_V1":
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_CONTRACT_INVALID")
        if production.get("model_id") != evidence.get("model_id") or production.get("feature_contract") != evidence.get("feature_contract"):
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_IDENTITY_MISMATCH")
        raw = production.get("signed_key_probability")
        if not isinstance(raw, dict):
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_PMF_REQUIRED")
        try:
            simulated_keys = {key: float(raw[str(key)]) for key in key_numbers}
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_PMF_INVALID") from exc
        if any(value < 0.0 or value > 1.0 for value in simulated_keys.values()):
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_PMF_INVALID")
        production_identity = {
            "contract": production["contract"],
            "model_id": production["model_id"],
            "feature_contract": production["feature_contract"],
            "probability_source": production.get("probability_source"),
            "heldout_game_count": int(production.get("heldout_game_count", 0)),
            "test_seasons": list(production.get("test_seasons") or []),
        }
        if production_identity["heldout_game_count"] <= 0 or not production_identity["test_seasons"]:
            raise SystemExit("NFL_PRODUCTION_KEY_PROFILE_SUPPORT_INVALID")
    else:
        # Compatibility-only candidate path. Production promotion must supply the
        # exact production evidence so this smooth simulator cannot certify M2.
        model = KeyNumberMarginModel(args.mean, args.sigma)
        pmf = model.margin_pmf(range(-80, 81))
        simulated_keys = {key: pmf[key] for key in key_numbers}
    fit = validate_profile_fit(profile, simulated_keys, max_abs_error=args.max_abs_error)
    math_artifact = build_math_attestation_artifact(profile, fit)
    attestation = attest_validated_math(math_artifact)

    payload = {
        "profile": profile,
        "fit": fit,
        "math_artifact": math_artifact,
        "math_attestation": attestation,
        "margin_mean": args.mean if args.production_evidence is None else None,
        "margin_sigma": args.sigma if args.production_evidence is None else None,
        "production_distribution_identity": production_identity,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    if args.require_pass and not attestation["math_valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
