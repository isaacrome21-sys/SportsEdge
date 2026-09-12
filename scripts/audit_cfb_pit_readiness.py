#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.sports.cfb.pit_readiness import CFBPITReadinessError, audit_cfb_pit_readiness


def _optional_path(value: str | None) -> Path | None:
    return None if value is None else Path(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed audit of CFB PIT and paired historical market evidence readiness."
    )
    parser.add_argument("--truth-gate", default="config/cfb_truth_gate_v1.json")
    parser.add_argument("--current-release-classification")
    parser.add_argument("--pit-source-manifest")
    parser.add_argument("--availability-proof")
    parser.add_argument("--paired-market-evidence")
    parser.add_argument("--evidence-root")
    parser.add_argument("--output", default="artifacts/cfb/pit_readiness.json")
    args = parser.parse_args()

    try:
        report = audit_cfb_pit_readiness(
            truth_gate_path=Path(args.truth_gate),
            current_release_classification_path=_optional_path(args.current_release_classification),
            pit_source_manifest_path=_optional_path(args.pit_source_manifest),
            availability_proof_path=_optional_path(args.availability_proof),
            paired_market_evidence_path=_optional_path(args.paired_market_evidence),
            evidence_root=_optional_path(args.evidence_root),
        )
    except CFBPITReadinessError as exc:
        raise SystemExit(f"CFB_PIT_READINESS_INVALID:{exc}") from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "state": report["readiness_state"],
                "blockers": report["blockers"],
                "historical_truth_gate_execution_allowed": report["historical_truth_gate_execution_allowed"],
                "forward_clock_allowed": report["forward_clock_allowed"],
                "promotion_authority": report["promotion_authority"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
