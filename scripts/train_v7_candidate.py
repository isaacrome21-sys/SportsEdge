#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sportsedge.v7_reduced_feature_contract import (
    DEFAULT_REDUCED_CONTRACT_PATH,
    load_reduced_feature_contract,
    project_full_payload_to_reduced,
)
from sportsedge.v7_training import train_chronological_candidate


POLICY_PATH = Path("config/v7_feature_backfill_policy_v1.json")
REQUIREMENTS_PATH = Path("config/v7_backfill_source_requirements_v1.json")
REDUCED_CONTRACT_PATH = DEFAULT_REDUCED_CONTRACT_PATH


def _load(path: Path):
    try:
        value = json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"V7_TRAINING_DATA_INVALID:{path}") from exc
    if not isinstance(value, list):
        raise SystemExit("V7_TRAINING_DATA_MUST_BE_LIST")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_source_readiness(path: Path, reduced_contract: dict) -> dict:
    try:
        report = json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"V7_SOURCE_READINESS_REPORT_INVALID:{path}") from exc
    if not isinstance(report, dict): raise SystemExit("V7_SOURCE_READINESS_REPORT_MUST_BE_OBJECT")
    if report.get("contract") != "SPORTSEDGE_MLB_V7_BACKFILL_SOURCE_READINESS_V1": raise SystemExit("V7_SOURCE_READINESS_CONTRACT_MISMATCH")
    if report.get("policy_sha256") != _sha256(POLICY_PATH): raise SystemExit("V7_SOURCE_READINESS_POLICY_SHA256_MISMATCH")
    if report.get("requirements_sha256") != _sha256(REQUIREMENTS_PATH): raise SystemExit("V7_SOURCE_READINESS_REQUIREMENTS_SHA256_MISMATCH")
    if report.get("admitted_feature_count") != 12: raise SystemExit("V7_SOURCE_READINESS_ADMITTED_COUNT_MISMATCH")
    if report.get("source_ready_feature_count") != 12: raise SystemExit("V7_SOURCE_READINESS_INCOMPLETE")
    if report.get("source_readiness_state") != "READY_SOURCE_COVERAGE": raise SystemExit("V7_SOURCE_READINESS_NOT_READY")
    if report.get("reduced_feature_contract_ready") is not True: raise SystemExit("V7_REDUCED_FEATURE_CONTRACT_NOT_FROZEN")
    if report.get("reduced_feature_contract_file_sha256") != reduced_contract["contract_file_sha256"]: raise SystemExit("V7_REDUCED_FEATURE_CONTRACT_FILE_SHA256_MISMATCH")
    if report.get("reduced_feature_contract_sha256") != reduced_contract["feature_contract_sha256"]: raise SystemExit("V7_REDUCED_FEATURE_CONTRACT_SHA256_MISMATCH")
    if report.get("reduced_feature_paths") != list(reduced_contract["feature_paths"]): raise SystemExit("V7_REDUCED_FEATURE_PATHS_MISMATCH")
    if report.get("candidate_training_allowed") is not True: raise SystemExit("V7_CANDIDATE_TRAINING_NOT_AUTHORIZED")
    return report


def _project_rows(rows: list, reduced_contract: dict) -> list[dict]:
    projected = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict): raise SystemExit(f"V7_TRAINING_ROW_INVALID:{index}")
        payload = raw.get("feature_payload")
        if not isinstance(payload, dict): raise SystemExit(f"V7_TRAINING_FEATURE_PAYLOAD_MISSING:{index}")
        row = dict(raw)
        row["feature_payload"] = project_full_payload_to_reduced(payload, contract=reduced_contract)
        projected.append(row)
    return projected


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and freeze a chronological V7 candidate from predeclared historical feature rows.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--source-readiness-report", required=True)
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
    reduced_contract = load_reduced_feature_contract(REDUCED_CONTRACT_PATH, policy_path=POLICY_PATH, requirements_path=REQUIREMENTS_PATH)
    readiness = _require_source_readiness(Path(args.source_readiness_report), reduced_contract)
    rows = _project_rows(_load(Path(args.input)), reduced_contract)
    candidate, report = train_chronological_candidate(rows, model_name=args.model_name, train_end=args.train_end, calibration_start=args.calibration_start, calibration_end=args.calibration_end, holdout_start=args.holdout_start, feature_paths=reduced_contract["feature_paths"], feature_contract_sha256=reduced_contract["feature_contract_sha256"], l2=args.l2, iterations=args.iterations, learning_rate=args.learning_rate)
    report["source_readiness_report"] = {"data_ref": readiness.get("data_ref"), "policy_sha256": readiness["policy_sha256"], "requirements_sha256": readiness["requirements_sha256"], "source_ready_feature_count": readiness["source_ready_feature_count"], "reduced_feature_contract_file_sha256": readiness["reduced_feature_contract_file_sha256"], "reduced_feature_contract_sha256": readiness["reduced_feature_contract_sha256"]}
    candidate_path, report_path = Path(args.candidate_output), Path(args.report_output)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(candidate, sort_keys=True, indent=2) + "\n")
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"state": "FROZEN", "candidate_sha256": candidate["candidate_sha256"], "feature_contract_sha256": candidate["feature_contract_sha256"], "candidate_output": str(candidate_path), "report_output": str(report_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
