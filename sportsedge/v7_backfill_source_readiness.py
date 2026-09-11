from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class SourceReadinessError(RuntimeError):
    """Raised when the readiness contract itself is invalid or unverifiable."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except Exception as exc:
        raise SourceReadinessError(f"INVALID_JSON:{path}") from exc
    if not isinstance(value, dict):
        raise SourceReadinessError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _date_le(left: str, right: str) -> bool:
    # Frozen contracts use zero-padded ISO calendar dates, so lexical order is exact.
    return isinstance(left, str) and isinstance(right, str) and left <= right


def _safe_evidence_path(source_root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise SourceReadinessError("EVIDENCE_PATH_INVALID")
    root = source_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SourceReadinessError(f"EVIDENCE_PATH_ESCAPES_ROOT:{relative_path}") from exc
    return candidate


def _verify_source(
    source_root: Path,
    source_class: str,
    requirement: dict[str, Any],
    coverage_start: str,
    coverage_end: str,
) -> dict[str, Any]:
    manifest_rel = requirement.get("manifest_path")
    if not isinstance(manifest_rel, str) or not manifest_rel:
        raise SourceReadinessError(f"MANIFEST_PATH_REQUIRED:{source_class}")
    manifest_path = _safe_evidence_path(source_root, manifest_rel)
    result: dict[str, Any] = {
        "source_class": source_class,
        "manifest_path": manifest_rel,
        "ready": False,
        "reasons": [],
    }
    if not manifest_path.is_file():
        result["reasons"].append("ATTESTATION_MANIFEST_MISSING")
        return result

    manifest = _load_json(manifest_path)
    result["manifest_sha256"] = _sha256(manifest_path)
    if manifest.get("source_class") != source_class:
        result["reasons"].append("SOURCE_CLASS_MISMATCH")

    actual_start = manifest.get("coverage_start")
    actual_end = manifest.get("coverage_end")
    if not isinstance(actual_start, str) or not _date_le(actual_start, coverage_start):
        result["reasons"].append("COVERAGE_START_INSUFFICIENT")
    if not isinstance(actual_end, str) or not _date_le(coverage_end, actual_end):
        result["reasons"].append("COVERAGE_END_INSUFFICIENT")

    actual_fields = manifest.get("fields")
    if not isinstance(actual_fields, list):
        result["reasons"].append("FIELDS_ATTESTATION_MISSING")
    else:
        missing_fields = sorted(set(requirement.get("required_fields", [])) - set(actual_fields))
        if missing_fields:
            result["missing_fields"] = missing_fields
            result["reasons"].append("REQUIRED_FIELDS_MISSING")

    actual_semantics = manifest.get("semantics")
    if not isinstance(actual_semantics, dict):
        result["reasons"].append("SEMANTICS_ATTESTATION_MISSING")
    else:
        missing_semantics = {
            key: expected
            for key, expected in requirement.get("required_semantics", {}).items()
            if actual_semantics.get(key) != expected
        }
        if missing_semantics:
            result["missing_semantics"] = missing_semantics
            result["reasons"].append("REQUIRED_SEMANTICS_NOT_ATTESTED")

    evidence_files = manifest.get("evidence_files")
    if not isinstance(evidence_files, list) or not evidence_files:
        result["reasons"].append("HASH_BOUND_EVIDENCE_FILES_MISSING")
    else:
        evidence_errors: list[str] = []
        verified = 0
        for item in evidence_files:
            if not isinstance(item, dict):
                evidence_errors.append("INVALID_EVIDENCE_ENTRY")
                continue
            rel = item.get("path")
            expected_sha = item.get("sha256")
            try:
                evidence_path = _safe_evidence_path(source_root, rel)
            except SourceReadinessError as exc:
                evidence_errors.append(str(exc))
                continue
            if not evidence_path.is_file():
                evidence_errors.append(f"MISSING:{rel}")
                continue
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                evidence_errors.append(f"SHA256_INVALID:{rel}")
                continue
            actual_sha = _sha256(evidence_path)
            if actual_sha != expected_sha.lower():
                evidence_errors.append(f"SHA256_MISMATCH:{rel}")
                continue
            verified += 1
        result["verified_evidence_file_count"] = verified
        if evidence_errors:
            result["evidence_errors"] = evidence_errors
            result["reasons"].append("HASH_BOUND_EVIDENCE_VERIFICATION_FAILED")

    result["reasons"] = sorted(set(result["reasons"]))
    result["ready"] = not result["reasons"]
    return result


def audit_v7_backfill_source_readiness(
    *,
    policy_path: Path,
    requirements_path: Path,
    source_root: Path,
    data_ref: str,
) -> dict[str, Any]:
    if not source_root.is_dir():
        raise SourceReadinessError(f"SOURCE_ROOT_MISSING:{source_root}")

    policy = _load_json(policy_path)
    requirements = _load_json(requirements_path)
    if requirements.get("contract") != "SPORTSEDGE_MLB_V7_BACKFILL_SOURCE_READINESS_V1":
        raise SourceReadinessError("READINESS_CONTRACT_ID_MISMATCH")
    if requirements.get("policy_path") != str(policy_path.as_posix()):
        # Absolute/temp paths are permitted in tests; basename match still binds the intended policy file.
        if Path(str(requirements.get("policy_path", ""))).name != policy_path.name:
            raise SourceReadinessError("POLICY_PATH_BINDING_MISMATCH")

    approved = policy.get("initial_backfill_approval", {}).get("approved_paths")
    if not isinstance(approved, list) or not approved:
        raise SourceReadinessError("POLICY_APPROVED_PATHS_MISSING")
    groups = requirements.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise SourceReadinessError("READINESS_GROUPS_MISSING")

    required_paths: list[str] = []
    for group in groups.values():
        if not isinstance(group, dict) or not isinstance(group.get("feature_paths"), list):
            raise SourceReadinessError("GROUP_FEATURE_PATHS_INVALID")
        required_paths.extend(group["feature_paths"])
    if len(required_paths) != len(set(required_paths)):
        raise SourceReadinessError("DUPLICATE_FEATURE_PATH_IN_REQUIREMENTS")
    if set(required_paths) != set(approved):
        raise SourceReadinessError("POLICY_REQUIREMENTS_FEATURE_SET_MISMATCH")

    coverage = requirements.get("coverage", {})
    coverage_start = coverage.get("start")
    coverage_end = coverage.get("end")
    if not isinstance(coverage_start, str) or not isinstance(coverage_end, str) or coverage_start > coverage_end:
        raise SourceReadinessError("COVERAGE_WINDOW_INVALID")

    group_reports: dict[str, Any] = {}
    ready_paths: list[str] = []
    for group_name, group in groups.items():
        sources = group.get("sources")
        if not isinstance(sources, dict) or not sources:
            raise SourceReadinessError(f"GROUP_SOURCES_MISSING:{group_name}")
        source_reports = {
            source_class: _verify_source(source_root, source_class, source_req, coverage_start, coverage_end)
            for source_class, source_req in sorted(sources.items())
        }
        ready = all(item["ready"] for item in source_reports.values())
        feature_paths = list(group["feature_paths"])
        if ready:
            ready_paths.extend(feature_paths)
        group_reports[group_name] = {
            "ready": ready,
            "feature_paths": feature_paths,
            "sources": source_reports,
        }

    ready_paths = sorted(ready_paths)
    admitted_paths = sorted(approved)
    source_ready = len(ready_paths) == len(admitted_paths)
    blockers: list[str] = []
    if not source_ready:
        blockers.append("SOURCE_COVERAGE")
    # The existing trainer stamps the full 46-feature contract even when passed a subset.
    # Source readiness alone therefore cannot authorize a reduced 12-feature artifact.
    blockers.append("REDUCED_FEATURE_CONTRACT_NOT_FROZEN")

    discovered = sorted(p.name for p in source_root.iterdir() if p.is_dir())
    return {
        "contract": requirements["contract"],
        "data_ref": data_ref,
        "policy_sha256": _sha256(policy_path),
        "requirements_sha256": _sha256(requirements_path),
        "source_root": str(source_root),
        "discovered_source_directories": discovered,
        "admitted_feature_count": len(admitted_paths),
        "admitted_feature_paths": admitted_paths,
        "source_ready_feature_count": len(ready_paths),
        "source_ready_feature_paths": ready_paths,
        "source_readiness_state": "READY_SOURCE_COVERAGE" if source_ready else "BLOCKED_SOURCE_COVERAGE",
        "groups": group_reports,
        "reduced_feature_contract_ready": False,
        "candidate_training_allowed": False,
        "candidate_training_blockers": blockers,
        "promotion_authority": False,
    }
