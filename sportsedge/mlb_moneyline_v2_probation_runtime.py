"""Runtime CLI for the non-authoritative MLB MONEYLINE V2 PROBATION readiness gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .mlb_moneyline_v2_probation import (
    MLBMoneylineV2ProbationError,
    READINESS_SCHEMA,
    evaluate_probation_readiness,
)

DEFAULT_CHECKPOINT_REPORT = "artifacts/mlb_moneyline_v2_checkpoint_report.json"
DEFAULT_READINESS_REPORT = "artifacts/mlb_moneyline_v2_probation_readiness.json"


def _object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineV2ProbationError(f"{label} unreadable") from exc
    if not isinstance(value, dict):
        raise MLBMoneylineV2ProbationError(f"{label} must be an object")
    return value


def _write(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-report", default=DEFAULT_CHECKPOINT_REPORT)
    parser.add_argument("--prerequisite-attestation")
    parser.add_argument("--report", default=DEFAULT_READINESS_REPORT)
    args = parser.parse_args(argv)
    try:
        checkpoint = _object(args.checkpoint_report, "checkpoint report")
        attestation = (
            _object(args.prerequisite_attestation, "probation prerequisite attestation")
            if args.prerequisite_attestation
            else None
        )
        report = evaluate_probation_readiness(
            checkpoint,
            prerequisite_attestation=attestation,
        )
    except (OSError, MLBMoneylineV2ProbationError) as exc:
        blocked = {
            "schema_version": READINESS_SCHEMA,
            "status": "BLOCKED_PROBATION_READINESS_INTEGRITY_ERROR",
            "reason": str(exc),
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
            "transition_ready_for_authority_review": False,
        }
        _write(args.report, blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2
    _write(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
