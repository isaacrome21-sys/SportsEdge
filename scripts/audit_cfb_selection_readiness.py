#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.sports.cfb.acquisition_readiness import audit_cfb_acquisition_readiness
from sportsedge.sports.cfb.selection_readiness import audit_cfb_selection_readiness


def _load(path: str | None):
    if not path:
        return None
    source = Path(path)
    return json.loads(source.read_text(encoding="utf-8")) if source.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit reconstructed CFB first-evaluation readiness.")
    parser.add_argument("--policy", default="config/cfb_model_selection_policy_v1.json")
    parser.add_argument("--prereg", default="config/cfb_model_candidate_prereg_v1.json")
    parser.add_argument("--prereg-report", required=True)
    parser.add_argument("--freeze", default="config/cfb_game_model_freeze.json")
    parser.add_argument("--acquisition-manifest")
    parser.add_argument("--selection-bundle")
    parser.add_argument("--acquisition-out", default="artifacts/cfb/acquisition_readiness.json")
    parser.add_argument("--out", default="artifacts/cfb/first_evaluation_readiness.json")
    args = parser.parse_args()

    policy = _load(args.policy)
    prereg = _load(args.prereg)
    prereg_report = _load(args.prereg_report)
    freeze = _load(args.freeze)
    if not all(isinstance(value, dict) for value in (policy, prereg, prereg_report, freeze)):
        raise SystemExit("CFB_SELECTION_READINESS_REQUIRED_CONFIG_MISSING")

    acquisition = audit_cfb_acquisition_readiness(policy, _load(args.acquisition_manifest))
    report = audit_cfb_selection_readiness(
        policy=policy,
        preregistration=prereg,
        prereg_report=prereg_report,
        freeze_registry=freeze,
        acquisition_report=acquisition,
        selection_bundle=_load(args.selection_bundle),
    )

    acquisition_out = Path(args.acquisition_out)
    acquisition_out.parent.mkdir(parents=True, exist_ok=True)
    acquisition_out.write_text(json.dumps(acquisition, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "blockers": report["blockers"], "output": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
