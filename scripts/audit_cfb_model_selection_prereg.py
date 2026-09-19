#!/usr/bin/env python3
"""Audit CFB model-selection preregistration without fitting or scoring a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.sports.cfb.model_selection_prereg import audit_model_selection_prereg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="config/cfb_model_selection_policy_v1.json")
    parser.add_argument("--prereg", default="config/cfb_model_candidate_prereg_v1.json")
    parser.add_argument("--out")
    args = parser.parse_args()

    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    prereg_path = Path(args.prereg)
    prereg = json.loads(prereg_path.read_text(encoding="utf-8")) if prereg_path.exists() else None
    report = audit_model_selection_prereg(policy, prereg)
    if prereg is None:
        report["preregistration_path"] = str(prereg_path)
        report["preregistration_file_present"] = False
    else:
        report["preregistration_path"] = str(prereg_path)
        report["preregistration_file_present"] = True

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "READY_FOR_FIRST_EVALUATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
