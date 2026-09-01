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
    parser.add_argument("--out", type=Path, default=Path("artifacts/nfl_simulator_profile.json"))
    args = parser.parse_args()

    audit = json.loads(args.audit_json.read_text())
    profile = build_nfl_simulator_profile(audit, version=args.version)

    # The historical target is deliberately not supplied to the simulator.
    model = KeyNumberMarginModel(args.mean, args.sigma)
    pmf = model.margin_pmf(range(-80, 81))
    key_numbers = tuple(sorted(int(key) for key in profile["validation_target_key_frequency"]))
    simulated_keys = {key: pmf[key] for key in key_numbers}
    fit = validate_profile_fit(profile, simulated_keys, max_abs_error=args.max_abs_error)
    math_artifact = build_math_attestation_artifact(profile, fit)
    attestation = attest_validated_math(math_artifact)

    payload = {
        "profile": profile,
        "fit": fit,
        "math_artifact": math_artifact,
        "math_attestation": attestation,
        "margin_mean": args.mean,
        "margin_sigma": args.sigma,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    if args.require_pass and not attestation["math_valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
