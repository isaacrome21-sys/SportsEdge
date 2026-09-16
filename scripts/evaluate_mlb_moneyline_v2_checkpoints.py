#!/usr/bin/env python3
"""Evaluate fixed MLB MONEYLINE V2 checkpoints and freeze deterministic receipts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.sports.mlb.moneyline_v2_checkpoint import (  # noqa: E402
    MLBMoneylineV2CheckpointError,
    evaluate_v2_checkpoints,
)

DEFAULT_EVIDENCE_ROOT = "data/mlb_forward_evidence"
DEFAULT_RECEIPT_ROOT = "data/mlb_forward_checkpoint_receipts"
DEFAULT_REPORT = "artifacts/mlb_moneyline_v2_checkpoint_report.json"


def _json_files(root: str | Path) -> list[dict[str, Any]]:
    path = Path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*.json")):
        try:
            value = json.loads(item.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MLBMoneylineV2CheckpointError(f"invalid JSON: {item}") from exc
        if not isinstance(value, dict):
            raise MLBMoneylineV2CheckpointError(f"JSON object required: {item}")
        if value.get("status") == "FORWARD_EVIDENCE_COMPLETE_V2":
            rows.append(value)
    return rows


def _canonical_pretty(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_create_only(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise MLBMoneylineV2CheckpointError(f"immutable checkpoint receipt collision: {path}")
        return "ALREADY_PRESENT"
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise MLBMoneylineV2CheckpointError(f"immutable checkpoint receipt collision: {path}")
        return "ALREADY_PRESENT"
    return "CREATED"


def evaluate_from_disk(
    *,
    evidence_root: str | Path = DEFAULT_EVIDENCE_ROOT,
    receipt_root: str | Path = DEFAULT_RECEIPT_ROOT,
    report_path: str | Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    result = evaluate_v2_checkpoints(_json_files(evidence_root))
    writes: list[dict[str, str]] = []
    for receipt in result["checkpoint_receipts"]:
        count = int(receipt["checkpoint_graded_count"])
        artifact = str(receipt["model_artifact_sha256"])
        path = Path(receipt_root) / artifact / f"checkpoint_{count}.json"
        disposition = _write_create_only(path, _canonical_pretty(receipt))
        writes.append({"path": str(path), "disposition": disposition})
    report = {**result, "receipt_writes": writes}
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--receipt-root", default=DEFAULT_RECEIPT_ROOT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = evaluate_from_disk(
            evidence_root=args.evidence_root,
            receipt_root=args.receipt_root,
            report_path=args.report,
        )
    except MLBMoneylineV2CheckpointError as exc:
        print(json.dumps({"status": "BLOCKED_CHECKPOINT_EVALUATOR", "reason": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
