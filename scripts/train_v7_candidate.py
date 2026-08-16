#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.v7_training import train_chronological_candidate


def _load(path: Path):
    try:
        value = json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"V7_TRAINING_DATA_INVALID:{path}") from exc
    if not isinstance(value, list):
        raise SystemExit("V7_TRAINING_DATA_MUST_BE_LIST")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and freeze a chronological V7 candidate from predeclared historical feature rows.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--calibration-start", required=True)
    parser.add_argument("--calibration-end", required=True)
    parser.add_argument("--holdout-start", required=True)
    parser.add_argument("--candidate-output", default="artifacts/v7-shadow-state/candidate.json")
    parser.add_argument("--report-output", default="artifacts/v7-shadow-state/training_report.json")
    parser.add_argument("--l2", type=float, default=1.0)
    parser.add_argument("--iterations", type=int, default=1200)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    args = parser.parse_args()

    rows = _load(Path(args.input))
    candidate, report = train_chronological_candidate(
        rows,
        model_name=args.model_name,
        train_end=args.train_end,
        calibration_start=args.calibration_start,
        calibration_end=args.calibration_end,
        holdout_start=args.holdout_start,
        l2=args.l2,
        iterations=args.iterations,
        learning_rate=args.learning_rate,
    )

    candidate_path = Path(args.candidate_output)
    report_path = Path(args.report_output)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(candidate, sort_keys=True, indent=2) + "\n")
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "state": "FROZEN",
        "candidate_sha256": candidate["candidate_sha256"],
        "feature_contract_sha256": candidate["feature_contract_sha256"],
        "candidate_output": str(candidate_path),
        "report_output": str(report_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
