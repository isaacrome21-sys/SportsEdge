#!/usr/bin/env python3
"""Build a versioned NFL key-number profile from a real audit artifact and validate its PMF."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.core.simulate.football import KeyNumberMarginModel
from sportsedge.sports.nfl.simulator_profile import build_nfl_simulator_profile, validate_profile_fit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("--version", default="nfl-key-pmf-v1")
    parser.add_argument("--mean", type=float, default=0.0)
    parser.add_argument("--sigma", type=float, default=13.5)
    parser.add_argument("--max-abs-error", type=float, default=1e-12)
    parser.add_argument("--out", type=Path, default=Path("artifacts/nfl_simulator_profile.json"))
    args = parser.parse_args()

    audit = json.loads(args.audit_json.read_text())
    profile = build_nfl_simulator_profile(audit, version=args.version)
    model = KeyNumberMarginModel(args.mean, args.sigma, profile["empirical_key_mass"])
    pmf = model.margin_pmf(range(-80, 81))
    simulated_keys = {key: pmf[key] for key in profile["empirical_key_mass"]}
    fit = validate_profile_fit(profile, simulated_keys, max_abs_error=args.max_abs_error)
    payload = {"profile": profile, "fit": fit, "margin_mean": args.mean, "margin_sigma": args.sigma}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0 if fit["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
