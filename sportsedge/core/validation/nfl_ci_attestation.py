"""External attestation contract for the NFL promotion evidence workflow.

The evidence-producing workflow cannot attest itself.  This module is intended
for a *separate* workflow triggered by ``workflow_run``.  It binds a successful
named upstream run to the exact code SHA and verifies every hashed artifact
before any caller is allowed to rebuild the promotion registry with
``ci_attested=True``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_EXPECTED_WORKFLOW = "football-nfl-promotion-evidence"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"NFL_CI_ARTIFACT_JSON_INVALID:{path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"NFL_CI_ARTIFACT_NOT_OBJECT:{path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"NFL_CI_ARTIFACT_MISSING:{path.name}") from exc
    return digest.hexdigest()


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _hash(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def verify_nfl_pre_ci_bundle(
    bundle_dir: Path | str,
    *,
    workflow_name: str,
    workflow_conclusion: str,
    workflow_head_sha: str,
    workflow_run_id: int,
) -> dict[str, Any]:
    """Verify exact upstream-run identity plus all pre-CI evidence bytes."""
    if str(workflow_name) != _EXPECTED_WORKFLOW:
        raise ValueError("NFL_CI_WORKFLOW_NAME_MISMATCH")
    if str(workflow_conclusion).strip().lower() != "success":
        raise ValueError("NFL_CI_WORKFLOW_NOT_SUCCESSFUL")
    try:
        run_id = int(workflow_run_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("NFL_CI_WORKFLOW_RUN_ID_INVALID") from exc
    if run_id <= 0:
        raise ValueError("NFL_CI_WORKFLOW_RUN_ID_INVALID")
    head_sha = _git_sha(workflow_head_sha, "NFL_CI_WORKFLOW_HEAD_SHA_INVALID")

    root = Path(bundle_dir)
    manifest_path = root / "nfl_promotion_evidence_manifest.json"
    manifest = _json(manifest_path)
    if int(manifest.get("schema_version", 0)) != 2:
        raise ValueError("NFL_CI_EVIDENCE_MANIFEST_SCHEMA_INVALID")
    if manifest.get("ci_attestation_state") != "PRE_CI_WORKFLOW_CANNOT_SELF_ATTEST":
        raise ValueError("NFL_CI_PRE_ATTESTATION_STATE_INVALID")
    manifest_git_sha = _git_sha(manifest.get("git_sha"), "NFL_CI_EVIDENCE_GIT_SHA_INVALID")
    if manifest_git_sha != head_sha:
        raise ValueError("NFL_CI_HEAD_SHA_MISMATCH")
    source_manifest_sha = _hash(
        manifest.get("source_manifest_sha256"),
        "NFL_CI_SOURCE_MANIFEST_SHA256_INVALID",
    )

    artifact_rows = manifest.get("artifacts")
    if not isinstance(artifact_rows, list) or not artifact_rows:
        raise ValueError("NFL_CI_ARTIFACT_MANIFEST_EMPTY")
    seen: set[str] = set()
    for row in artifact_rows:
        if not isinstance(row, dict):
            raise ValueError("NFL_CI_ARTIFACT_MANIFEST_ROW_INVALID")
        name = str(row.get("path") or "").strip()
        if not name or Path(name).name != name or name in seen:
            raise ValueError("NFL_CI_ARTIFACT_PATH_INVALID")
        seen.add(name)
        expected = _hash(row.get("sha256"), f"NFL_CI_ARTIFACT_SHA256_INVALID:{name}")
        actual = _sha256(root / name)
        if actual != expected:
            raise ValueError(f"NFL_CI_ARTIFACT_HASH_MISMATCH:{name}")

    required = {
        "nfl_simulator_profile.json",
        "nfl_production_validation.json",
        "nfl_promotion_registry.json",
        "nfl_source_manifest.json",
    }
    if not required.issubset(seen):
        missing = sorted(required - seen)[0]
        raise ValueError(f"NFL_CI_REQUIRED_ARTIFACT_MISSING:{missing}")

    math_payload = _json(root / "nfl_simulator_profile.json")
    math = math_payload.get("math_artifact", math_payload)
    if not isinstance(math, dict):
        raise ValueError("NFL_CI_MATH_ARTIFACT_INVALID")
    history = _json(root / "nfl_production_validation.json")
    registry = _json(root / "nfl_promotion_registry.json")
    source_manifest = _json(root / "nfl_source_manifest.json")

    if _hash(math.get("source_sha256"), "NFL_CI_MATH_SOURCE_SHA256_INVALID") != source_manifest_sha:
        raise ValueError("NFL_CI_SOURCE_IDENTITY_MISMATCH")
    if _hash(history.get("source_sha256"), "NFL_CI_HISTORY_SOURCE_SHA256_INVALID") != source_manifest_sha:
        raise ValueError("NFL_CI_SOURCE_IDENTITY_MISMATCH")
    if _hash(history.get("source_manifest_sha256"), "NFL_CI_HISTORY_MANIFEST_SHA256_INVALID") != source_manifest_sha:
        raise ValueError("NFL_CI_SOURCE_IDENTITY_MISMATCH")
    if _hash(source_manifest.get("manifest_sha256"), "NFL_CI_SOURCE_MANIFEST_SELF_SHA_INVALID") != source_manifest_sha:
        raise ValueError("NFL_CI_SOURCE_IDENTITY_MISMATCH")

    math_code_sha = _git_sha(math.get("code_git_sha"), "NFL_CI_MATH_CODE_SHA_INVALID")
    history_code_sha = _git_sha(history.get("code_git_sha"), "NFL_CI_HISTORY_CODE_SHA_INVALID")
    if math_code_sha != head_sha or history_code_sha != head_sha:
        raise ValueError("NFL_CI_EVIDENCE_CODE_SHA_MISMATCH")

    for payload in (history, registry):
        if payload.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
            raise ValueError("NFL_CI_MODEL_ID_MISMATCH")
        if payload.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
            raise ValueError("NFL_CI_FEATURE_CONTRACT_MISMATCH")
    if registry.get("ci_attestation_state") != "UNATTESTED_IN_RUNNING_WORKFLOW":
        raise ValueError("NFL_CI_PRE_REGISTRY_STATE_INVALID")

    return {
        "schema_version": 1,
        "workflow_name": _EXPECTED_WORKFLOW,
        "workflow_conclusion": "success",
        "workflow_run_id": run_id,
        "git_sha": head_sha,
        "source_manifest_sha256": source_manifest_sha,
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "verified_artifact_count": len(seen),
    }
