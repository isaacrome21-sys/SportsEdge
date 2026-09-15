#!/usr/bin/env python3
"""Bind an MLB V8 replay archive to a deterministic byte receipt.

Run after ``build_mlb_v8_replay_archive.py``.  This is intentionally separate
from the frozen replay policy and archive builder: it strengthens reproducible
provenance without changing evidence-selection semantics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.core.validation.evidence_receipt import build_receipt, write_receipt

DEFAULT_POLICY = "config/mlb_v8_evidence_policy.json"
DEFAULT_INPUT = "artifacts/mlb_v8_replay_sources"
DEFAULT_OUTPUT = "artifacts/mlb_v8_replay_archive"


def _all_files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--input-root", default=DEFAULT_INPUT)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT)
    parser.add_argument("--receipt", default="artifacts/mlb_v8_replay_archive/receipt.json")
    args = parser.parse_args(argv)

    root = Path(args.root)
    input_root = root / args.input_root
    output_root = root / args.output_root
    policy = root / args.policy
    required_outputs = [output_root / "manifest.json", output_root / "gap_report.json"]

    missing = [p.relative_to(root).as_posix() for p in [policy, *required_outputs] if not p.is_file()]
    if missing:
        print(json.dumps({"status": "BLOCKED", "blockers": [f"MISSING:{p}" for p in missing]}, sort_keys=True))
        return 3

    inputs = _all_files(input_root)
    if not inputs:
        print(json.dumps({"status": "BLOCKED", "blockers": ["REPLAY_INPUTS_MISSING"]}, sort_keys=True))
        return 3

    receipt_path = root / args.receipt
    receipt = build_receipt(
        lane="MLB_V8_REPLAY",
        root=root,
        inputs=inputs,
        outputs=required_outputs,
        policy_path=policy,
        metadata={
            "selection_semantics": "EARLY_ONLY_AT_OR_BEFORE_TARGET",
            "receipt_scope": "raw_inputs_plus_manifest_plus_gap_report",
            "retroactive_evidence_allowed": False,
        },
    )
    write_receipt(receipt_path, receipt)
    print(json.dumps({"status": "PASS", "receipt": args.receipt, "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
