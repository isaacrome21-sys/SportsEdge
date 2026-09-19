#!/usr/bin/env python3
"""Audit CFB model-selection preregistration without fitting or scoring a model."""
from __future__ import annotations

import argparse
import json
from hashlib import sha1
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

    # The first evaluation now has an executable, pre-frozen evaluator contract.
    # Verify the exact evaluator bytes here so CFB readiness cannot approve a
    # different implementation from the one frozen before outcomes are seen.
    evaluator_contract_path = Path("config/cfb_candidate_bakeoff_evaluator_v1.json")
    if evaluator_contract_path.is_file():
        evaluator_contract = json.loads(evaluator_contract_path.read_text(encoding="utf-8"))
        evaluator_path = Path(str(evaluator_contract.get("evaluator_path") or ""))
        if not evaluator_path.is_file():
            report["status"] = "BLOCKED_EVALUATOR_CONTRACT"
            report.setdefault("blockers", []).append("CFB_BAKEOFF_EVALUATOR_MISSING")
        else:
            raw = evaluator_path.read_bytes()
            blob = sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
            if (
                evaluator_contract.get("status") != "FROZEN_BEFORE_FIRST_EVALUATION"
                or blob != evaluator_contract.get("evaluator_code_git_blob")
            ):
                report["status"] = "BLOCKED_EVALUATOR_CONTRACT"
                report.setdefault("blockers", []).append("CFB_BAKEOFF_EVALUATOR_BINDING_MISMATCH")
            else:
                report["bakeoff_evaluator_contract"] = "FROZEN_AND_BYTE_BOUND"
                report["bakeoff_evaluator_code_git_blob"] = blob
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
