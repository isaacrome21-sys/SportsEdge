"""External authenticity attestation for NFL forward-CLV evidence.

Internal hashes prove self-consistency, not that observations were genuinely
captured before kickoff. Promotion therefore accepts forward CLV only after a
separate scheduled workflow on ``main`` has produced the decision/close bundle
and this verifier has bound those exact bytes to the successful workflow run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_EXPECTED_WORKFLOW = "football-nfl-forward-clv-collection"
_EXPECTED_EVENT = "schedule"
_EXPECTED_BRANCH = "main"
_EXPECTED_COLLECTOR_CONTRACT = "NFL_FORWARD_CLV_COLLECTION_V1"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_ARTIFACTS = {
    "nfl_forward_decisions.jsonl",
    "nfl_forward_closes.jsonl",
    "nfl_clv_evidence.json",
}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"NFL_FORWARD_CLV_JSON_INVALID:{path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"NFL_FORWARD_CLV_JSON_NOT_OBJECT:{path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_MISSING:{path.name}") from exc
    return digest.hexdigest()


def _hash(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _count(value: Any, error: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(error)
    return value


def _jsonl_identities(path: Path, *, expected_git_sha: str, kind: str) -> tuple[int, set[tuple[str, str, str, str]], set[tuple[str, str, str]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_MISSING:{path.name}") from exc
    keys: set[tuple[str, str, str, str]] = set()
    observations: set[tuple[str, str, str]] = set()
    count = 0
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_JSON_INVALID:{number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_ROW_NOT_OBJECT:{number}")
        count += 1
        if str(row.get("sport") or "").strip().lower() != "nfl":
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_SPORT_INVALID:{number}")
        if row.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_MODEL_ID_MISMATCH:{number}")
        if row.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_FEATURE_CONTRACT_MISMATCH:{number}")
        row_sha = _git_sha(row.get("code_git_sha"), f"NFL_FORWARD_CLV_{kind}_CODE_SHA_INVALID:{number}")
        if row_sha != expected_git_sha:
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_CODE_SHA_MISMATCH:{number}")
        game_id = str(row.get("game_id") or "").strip()
        market = str(row.get("market") or "").strip().lower()
        side = str(row.get("side") or "").strip()
        book = str(row.get("book") or "").strip().lower()
        if not game_id or not market or not side or not book:
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_IDENTITY_MISSING:{number}")
        key = (game_id, market, side, book)
        observation = key[:3]
        if key in keys:
            raise ValueError(f"NFL_FORWARD_CLV_{kind}_DUPLICATE_KEY:{number}")
        if kind == "DECISION" and observation in observations:
            raise ValueError(f"NFL_FORWARD_CLV_DUPLICATE_OBSERVATION:{number}")
        keys.add(key)
        observations.add(observation)
    if count <= 0:
        raise ValueError(f"NFL_FORWARD_CLV_{kind}_LOG_EMPTY")
    return count, keys, observations


def canonical_clv_payload_sha256(payload: Mapping[str, Any]) -> str:
    """Hash semantic CLV content independently of JSON whitespace formatting."""
    material = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def verify_nfl_forward_clv_bundle(
    bundle_dir: Path | str,
    *,
    workflow_name: str,
    workflow_conclusion: str,
    workflow_event: str,
    workflow_head_branch: str,
    workflow_head_sha: str,
    workflow_run_id: int,
) -> dict[str, Any]:
    """Bind exact forward logs/evidence to an authentic scheduled main run."""
    if str(workflow_name) != _EXPECTED_WORKFLOW:
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NAME_MISMATCH")
    if str(workflow_conclusion).strip().lower() != "success":
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NOT_SUCCESSFUL")
    if str(workflow_event).strip().lower() != _EXPECTED_EVENT:
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_EVENT_INVALID")
    if str(workflow_head_branch).strip() != _EXPECTED_BRANCH:
        raise ValueError("NFL_FORWARD_CLV_HEAD_BRANCH_INVALID")
    try:
        run_id = int(workflow_run_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID") from exc
    if run_id <= 0:
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID")
    head_sha = _git_sha(workflow_head_sha, "NFL_FORWARD_CLV_WORKFLOW_HEAD_SHA_INVALID")

    root = Path(bundle_dir)
    manifest = _json(root / "nfl_forward_clv_manifest.json")
    if int(manifest.get("schema_version", 0)) != 1:
        raise ValueError("NFL_FORWARD_CLV_MANIFEST_SCHEMA_INVALID")
    if manifest.get("collector_contract") != _EXPECTED_COLLECTOR_CONTRACT:
        raise ValueError("NFL_FORWARD_CLV_COLLECTOR_CONTRACT_INVALID")
    manifest_sha = _git_sha(manifest.get("git_sha"), "NFL_FORWARD_CLV_MANIFEST_GIT_SHA_INVALID")
    if manifest_sha != head_sha:
        raise ValueError("NFL_FORWARD_CLV_HEAD_SHA_MISMATCH")
    if manifest.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_FORWARD_CLV_MODEL_ID_MISMATCH")
    if manifest.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_FORWARD_CLV_FEATURE_CONTRACT_MISMATCH")

    artifact_rows = manifest.get("artifacts")
    if not isinstance(artifact_rows, list) or not artifact_rows:
        raise ValueError("NFL_FORWARD_CLV_ARTIFACT_MANIFEST_EMPTY")
    seen: dict[str, str] = {}
    for row in artifact_rows:
        if not isinstance(row, dict):
            raise ValueError("NFL_FORWARD_CLV_ARTIFACT_MANIFEST_ROW_INVALID")
        name = str(row.get("path") or "").strip()
        if not name or Path(name).name != name or name in seen:
            raise ValueError("NFL_FORWARD_CLV_ARTIFACT_PATH_INVALID")
        expected = _hash(row.get("sha256"), f"NFL_FORWARD_CLV_ARTIFACT_SHA256_INVALID:{name}")
        actual = _sha256(root / name)
        if actual != expected:
            raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_HASH_MISMATCH:{name}")
        seen[name] = actual
    missing = sorted(_REQUIRED_ARTIFACTS - set(seen))
    if missing:
        raise ValueError(f"NFL_FORWARD_CLV_REQUIRED_ARTIFACT_MISSING:{missing[0]}")

    evidence = _json(root / "nfl_clv_evidence.json")
    if int(evidence.get("schema_version", 0)) != 4:
        raise ValueError("NFL_FORWARD_CLV_EVIDENCE_SCHEMA_INVALID")
    if str(evidence.get("sport") or "").strip().lower() != "nfl":
        raise ValueError("NFL_FORWARD_CLV_EVIDENCE_SPORT_INVALID")
    if evidence.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_FORWARD_CLV_MODEL_ID_MISMATCH")
    if evidence.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_FORWARD_CLV_FEATURE_CONTRACT_MISMATCH")
    evidence_sha = _git_sha(evidence.get("code_git_sha"), "NFL_FORWARD_CLV_EVIDENCE_GIT_SHA_INVALID")
    if evidence_sha != head_sha:
        raise ValueError("NFL_FORWARD_CLV_EVIDENCE_CODE_SHA_MISMATCH")

    decision_hash = _hash(
        evidence.get("decision_log_sha256"), "NFL_FORWARD_CLV_DECISION_LOG_SHA256_INVALID"
    )
    close_hash = _hash(
        evidence.get("close_log_sha256"), "NFL_FORWARD_CLV_CLOSE_LOG_SHA256_INVALID"
    )
    if decision_hash != seen["nfl_forward_decisions.jsonl"]:
        raise ValueError("NFL_FORWARD_CLV_DECISION_LOG_IDENTITY_MISMATCH")
    if close_hash != seen["nfl_forward_closes.jsonl"]:
        raise ValueError("NFL_FORWARD_CLV_CLOSE_LOG_IDENTITY_MISMATCH")

    decision_rows, decision_keys, decision_observations = _jsonl_identities(
        root / "nfl_forward_decisions.jsonl", expected_git_sha=head_sha, kind="DECISION"
    )
    close_rows, close_keys, close_observations = _jsonl_identities(
        root / "nfl_forward_closes.jsonl", expected_git_sha=head_sha, kind="CLOSE"
    )
    if decision_keys != close_keys:
        raise ValueError("NFL_FORWARD_CLV_DECISION_CLOSE_IDENTITY_MISMATCH")
    if decision_observations != close_observations:
        raise ValueError("NFL_FORWARD_CLV_OBSERVATION_IDENTITY_MISMATCH")

    decision_count = _count(evidence.get("decision_count"), "NFL_FORWARD_CLV_DECISION_COUNT_INVALID")
    close_count = _count(evidence.get("close_count"), "NFL_FORWARD_CLV_CLOSE_COUNT_INVALID")
    unique_count = _count(
        evidence.get("unique_observation_count"), "NFL_FORWARD_CLV_UNIQUE_COUNT_INVALID"
    )
    if decision_count != close_count or decision_count != unique_count:
        raise ValueError("NFL_FORWARD_CLV_COUNT_IDENTITY_MISMATCH")
    if decision_count != decision_rows:
        raise ValueError("NFL_FORWARD_CLV_DECISION_ROW_COUNT_MISMATCH")
    if close_count != close_rows:
        raise ValueError("NFL_FORWARD_CLV_CLOSE_ROW_COUNT_MISMATCH")
    if unique_count != len(decision_observations):
        raise ValueError("NFL_FORWARD_CLV_UNIQUE_ROW_COUNT_MISMATCH")
    if unique_count <= 0:
        raise ValueError("NFL_FORWARD_CLV_OBSERVATIONS_EMPTY")

    return {
        "schema_version": 1,
        "collector_contract": _EXPECTED_COLLECTOR_CONTRACT,
        "workflow_name": _EXPECTED_WORKFLOW,
        "workflow_conclusion": "success",
        "workflow_event": _EXPECTED_EVENT,
        "workflow_head_branch": _EXPECTED_BRANCH,
        "workflow_run_id": run_id,
        "git_sha": head_sha,
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "decision_log_sha256": decision_hash,
        "close_log_sha256": close_hash,
        "clv_payload_sha256": canonical_clv_payload_sha256(evidence),
        "decision_count": decision_count,
        "close_count": close_count,
        "unique_observation_count": unique_count,
        "verified_artifact_count": len(seen),
    }
