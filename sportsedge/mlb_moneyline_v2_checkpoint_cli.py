"""CLI wrapper for the fixed MLB MONEYLINE V2 checkpoint evaluator."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .mlb_moneyline_forward_lane import MLBMoneylineForwardLaneError, load_forward_lane_binding
from .mlb_moneyline_v2_checkpoint import MLBMoneylineV2CheckpointError, evaluate_v2_checkpoint

DEFAULT_EVIDENCE_ROOT = "data/mlb_forward_evidence"
DEFAULT_REPORT = "artifacts/mlb_moneyline_v2_checkpoint_report.json"


def _json_rows(root: str | Path) -> list[dict[str, Any]]:
    base = Path(root)
    if not base.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise MLBMoneylineV2CheckpointError(f"JSON object required: {path}")
        if value.get("status") == "FORWARD_EVIDENCE_COMPLETE_V2":
            rows.append(value)
    return rows


def _warning_statuses(path: str | None) -> dict[str, dict[str, Any]] | None:
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MLBMoneylineV2CheckpointError("warning status file must be an object")
    return {str(k): dict(v) for k, v in value.items() if isinstance(v, dict)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--warning-statuses")
    args = parser.parse_args(argv)
    try:
        binding = load_forward_lane_binding()
        report = evaluate_v2_checkpoint(
            _json_rows(args.evidence_root),
            binding=binding,
            warning_statuses=_warning_statuses(args.warning_statuses),
        )
    except (OSError, json.JSONDecodeError, MLBMoneylineForwardLaneError, MLBMoneylineV2CheckpointError) as exc:
        blocked = {
            "schema_version": "mlb_moneyline_v2_checkpoint_evaluator_v1",
            "status": "BLOCKED",
            "reason": str(exc),
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
