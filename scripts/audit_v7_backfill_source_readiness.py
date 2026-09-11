#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.v7_backfill_source_readiness import (
    SourceReadinessError,
    audit_v7_backfill_source_readiness,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit whether admitted MLB V7 backfill features have hash-bound historical sources.")
    parser.add_argument("--policy", default="config/v7_feature_backfill_policy_v1.json")
    parser.add_argument("--requirements", default="config/v7_backfill_source_requirements_v1.json")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--data-ref", required=True)
    parser.add_argument("--output", default="artifacts/v7-backfill-source-readiness/report.json")
    args = parser.parse_args()

    try:
        report = audit_v7_backfill_source_readiness(
            policy_path=Path(args.policy),
            requirements_path=Path(args.requirements),
            source_root=Path(args.source_root),
            data_ref=args.data_ref,
        )
    except SourceReadinessError as exc:
        raise SystemExit(f"V7_BACKFILL_SOURCE_READINESS_INVALID:{exc}") from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "state": report["source_readiness_state"],
        "source_ready_feature_count": report["source_ready_feature_count"],
        "admitted_feature_count": report["admitted_feature_count"],
        "candidate_training_allowed": report["candidate_training_allowed"],
        "candidate_training_blockers": report["candidate_training_blockers"],
        "data_ref": report["data_ref"],
        "output": str(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
