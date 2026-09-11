from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sportsedge.v7_backfill_source_readiness import SourceReadinessError, audit_v7_backfill_source_readiness

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "v7_feature_backfill_policy_v1.json"
REQUIREMENTS = ROOT / "config" / "v7_backfill_source_requirements_v1.json"
REDUCED = ROOT / "config" / "v7_reduced_feature_contract_v1.json"


def _sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def _audit(source_root: Path, requirements: Path = REQUIREMENTS, reduced: Path = REDUCED):
    return audit_v7_backfill_source_readiness(policy_path=POLICY, requirements_path=requirements, source_root=source_root, data_ref="test-data-ref", reduced_contract_path=reduced)


def _write_complete_attestations(source_root: Path) -> None:
    req = json.loads(REQUIREMENTS.read_text())
    for group in req["groups"].values():
        for source_class, source_req in group["sources"].items():
            evidence = source_root / "raw" / f"{source_class}.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps({"source_class": source_class}) + "\n")
            manifest = source_root / source_req["manifest_path"]
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"source_class": source_class, "coverage_start": "2023-01-01", "coverage_end": "2025-12-31", "fields": source_req["required_fields"], "semantics": source_req["required_semantics"], "evidence_files": [{"path": evidence.relative_to(source_root).as_posix(), "sha256": _sha(evidence)}]}, sort_keys=True) + "\n")


def test_schedule_only_archive_is_zero_of_twelve(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    (source_root / "MLB_STATSAPI" / "2026-09-11").mkdir(parents=True)
    (source_root / "MLB_STATSAPI" / "2026-09-11" / "schedule.json").write_text("{}\n")
    report = _audit(source_root)
    assert report["admitted_feature_count"] == 12
    assert report["source_ready_feature_count"] == 0
    assert report["source_readiness_state"] == "BLOCKED_SOURCE_COVERAGE"
    assert report["reduced_feature_contract_ready"] is True
    assert len(report["reduced_feature_contract_sha256"]) == 64
    assert report["candidate_training_allowed"] is False
    assert report["candidate_training_blockers"] == ["SOURCE_COVERAGE"]


def test_missing_source_root_fails_hard(tmp_path: Path) -> None:
    with pytest.raises(SourceReadinessError, match="SOURCE_ROOT_MISSING"): _audit(tmp_path / "missing")


def test_policy_requirement_feature_set_mismatch_fails_hard(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"; source_root.mkdir()
    req = json.loads(REQUIREMENTS.read_text()); req["groups"]["bullpen"]["feature_paths"] = req["groups"]["bullpen"]["feature_paths"][:-1]
    altered = tmp_path / REQUIREMENTS.name; altered.write_text(json.dumps(req))
    with pytest.raises(SourceReadinessError, match="POLICY_REQUIREMENTS_FEATURE_SET_MISMATCH"): _audit(source_root, altered)


def test_complete_hash_bound_sources_and_frozen_reduced_contract_authorize_candidate_training(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"; source_root.mkdir(); _write_complete_attestations(source_root)
    report = _audit(source_root)
    assert report["source_ready_feature_count"] == 12
    assert report["source_readiness_state"] == "READY_SOURCE_COVERAGE"
    assert all(group["ready"] for group in report["groups"].values())
    assert report["reduced_feature_contract_ready"] is True
    assert report["candidate_training_allowed"] is True
    assert report["candidate_training_blockers"] == []
    assert report["promotion_authority"] is False


def test_missing_reduced_contract_keeps_training_blocked(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"; source_root.mkdir(); _write_complete_attestations(source_root)
    report = _audit(source_root, reduced=tmp_path / "missing-contract.json")
    assert report["source_ready_feature_count"] == 12
    assert report["reduced_feature_contract_ready"] is False
    assert report["candidate_training_allowed"] is False
    assert report["candidate_training_blockers"] == ["REDUCED_FEATURE_CONTRACT_NOT_FROZEN"]


def test_tampered_reduced_contract_fails_hard(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"; source_root.mkdir()
    contract = json.loads(REDUCED.read_text()); contract["feature_paths"] = contract["feature_paths"][:-1]
    altered = tmp_path / REDUCED.name; altered.write_text(json.dumps(contract))
    with pytest.raises(SourceReadinessError, match="REDUCED_FEATURE_CONTRACT_INVALID"): _audit(source_root, reduced=altered)


def test_missing_final_before_decision_semantics_blocks_bullpen(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"; source_root.mkdir(); _write_complete_attestations(source_root)
    manifest_path = source_root / "attestations" / "BULLPEN_USAGE.json"
    manifest = json.loads(manifest_path.read_text()); manifest["semantics"].pop("final_before_decision"); manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    report = _audit(source_root)
    source = report["groups"]["bullpen"]["sources"]["BULLPEN_USAGE"]
    assert report["groups"]["bullpen"]["ready"] is False
    assert "REQUIRED_SEMANTICS_NOT_ATTESTED" in source["reasons"]
    assert report["source_ready_feature_count"] == 7
    assert report["candidate_training_allowed"] is False


def test_tampered_evidence_file_blocks_source(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"; source_root.mkdir(); _write_complete_attestations(source_root)
    evidence = source_root / "raw" / "PARK_RAW.json"; evidence.write_text("tampered\n")
    report = _audit(source_root); park = report["groups"]["park"]["sources"]["PARK_RAW"]
    assert "HASH_BOUND_EVIDENCE_VERIFICATION_FAILED" in park["reasons"]
    assert report["groups"]["park"]["ready"] is False
    assert report["source_ready_feature_count"] == 9
