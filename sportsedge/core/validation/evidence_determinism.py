"""Fail-closed byte determinism checks for promotion evidence.

The verifier is intentionally sport-agnostic. Promotion evidence is only
reproducible when the same code SHA and the same frozen source-manifest identity
produce byte-identical requested artifacts.

Byte identity is the sole output pass/fail gate. JSON semantic comparison exists
only as a post-mismatch diagnostic and can never turn byte-different artifacts
into PASS.

Status contract:
* PASS: every requested artifact is byte-identical and identity preconditions hold.
* FAIL: code/source identity matches, but at least one requested artifact differs
  at the byte level.
* BLOCKED: the comparison cannot prove like-for-like replay (missing artifact,
  malformed JSON, bad SHA, source-manifest mismatch, or invalid configuration).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable

SUPPORTED_SPORTS = frozenset({"mlb", "cfb", "nfl"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def canonical_json_bytes(value: Any) -> bytes:
    """Return a canonical JSON representation for mismatch diagnostics only."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_sha256(value: Any) -> str:
    """Hash canonical JSON semantics for mismatch diagnostics only."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"NON_FINITE_JSON_NUMBER:{value}")


def _load_json_bytes(value: bytes) -> Any:
    return json.loads(value.decode("utf-8"), parse_constant=_reject_nonfinite)


def _valid_artifact_name(name: str) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return False
    parsed = PurePosixPath(raw)
    return not parsed.is_absolute() and ".." not in parsed.parts and parsed.parts != (".",)


def _normalize_git_sha(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    return raw if _GIT_SHA_RE.fullmatch(raw) else None


def _normalize_sha256(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    return raw if _SHA256_RE.fullmatch(raw) else None


def _code_git_sha(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    values = [payload.get(key) for key in ("code_git_sha", "git_sha") if payload.get(key) not in (None, "")]
    normalized = {_normalize_git_sha(value) for value in values}
    if not values or None in normalized or len(normalized) != 1:
        return None
    return next(iter(normalized))


def _source_manifest_sha256(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    return _normalize_sha256(payload.get("source_manifest_sha256"))


def _pointer_token(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _display(value: Any, *, limit: int = 500) -> Any:
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(rendered) > limit:
            return rendered[:limit] + "...<truncated>"
    return value


def _diff_json(
    baseline: Any,
    candidate: Any,
    *,
    path: str,
    differences: list[dict[str, Any]],
    max_differences: int,
) -> bool:
    """Append deterministic JSON-pointer diagnostics; return True if truncated."""
    if len(differences) >= max_differences:
        return True
    if type(baseline) is not type(candidate):
        differences.append({
            "path": path or "/",
            "kind": "type_mismatch",
            "baseline_type": type(baseline).__name__,
            "candidate_type": type(candidate).__name__,
            "baseline": _display(baseline),
            "candidate": _display(candidate),
        })
        return len(differences) >= max_differences
    if isinstance(baseline, dict):
        keys = sorted(set(baseline) | set(candidate), key=str)
        for key in keys:
            child = f"{path}/{_pointer_token(key)}"
            if key not in baseline:
                differences.append({"path": child, "kind": "candidate_only", "candidate": _display(candidate[key])})
            elif key not in candidate:
                differences.append({"path": child, "kind": "baseline_only", "baseline": _display(baseline[key])})
            else:
                truncated = _diff_json(
                    baseline[key], candidate[key], path=child,
                    differences=differences, max_differences=max_differences,
                )
                if truncated:
                    return True
            if len(differences) >= max_differences:
                return True
        return False
    if isinstance(baseline, list):
        if len(baseline) != len(candidate):
            differences.append({
                "path": path or "/", "kind": "length_mismatch",
                "baseline_length": len(baseline), "candidate_length": len(candidate),
            })
            if len(differences) >= max_differences:
                return True
        for index, (left, right) in enumerate(zip(baseline, candidate)):
            truncated = _diff_json(
                left, right, path=f"{path}/{index}",
                differences=differences, max_differences=max_differences,
            )
            if truncated:
                return True
        return False
    if baseline != candidate:
        differences.append({
            "path": path or "/", "kind": "value_mismatch",
            "baseline": _display(baseline), "candidate": _display(candidate),
        })
    return len(differences) >= max_differences


def _base_report(
    *, sport: str, baseline_label: str, candidate_label: str,
    expected_git_sha: str, artifacts: list[str], identity_artifact: str,
    determinism_class: str, replay_scope: str, clock_perturbation: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "contract": "SPORTSEDGE_BYTE_EXACT_EVIDENCE_REPLAY_V2",
        "gate_basis": "BYTE_IDENTITY",
        "sport": sport,
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "determinism_class": determinism_class,
        "replay_scope": replay_scope,
        "clock_perturbation": clock_perturbation,
        "expected_git_sha": expected_git_sha,
        "identity_artifact": identity_artifact,
        "artifacts_requested": artifacts,
        "status": "BLOCKED",
        "failure_class": None,
        "reason": None,
        "source_manifest_sha256": None,
        "all_bytes_equal": False,
        "artifact_comparisons": [],
        "differences": [],
        "differences_truncated": False,
    }


def compare_evidence_directories(
    *,
    sport: str,
    baseline_dir: Path | str,
    candidate_dir: Path | str,
    artifacts: Iterable[str],
    identity_artifact: str,
    expected_git_sha: str,
    determinism_class: str,
    replay_scope: str,
    clock_perturbation: str | None = None,
    baseline_label: str = "ATTEMPT_001",
    candidate_label: str = "REPLAY",
    require_source_manifest: bool = True,
    max_differences: int = 100,
) -> dict[str, Any]:
    """Compare evidence directories with byte identity as the only output gate."""
    normalized_sport = str(sport or "").strip().lower()
    names = [str(name).strip() for name in artifacts]
    identity_name = str(identity_artifact or "").strip()
    expected = _normalize_git_sha(expected_git_sha)
    determinism_class_value = str(determinism_class or "").strip()
    replay_scope_value = str(replay_scope or "").strip()
    clock_perturbation_value = str(clock_perturbation).strip() if clock_perturbation is not None else None
    report = _base_report(
        sport=normalized_sport,
        baseline_label=str(baseline_label),
        candidate_label=str(candidate_label),
        expected_git_sha=str(expected_git_sha or "").strip().lower(),
        artifacts=names,
        identity_artifact=identity_name,
        determinism_class=determinism_class_value,
        replay_scope=replay_scope_value,
        clock_perturbation=clock_perturbation_value,
    )

    def blocked(reason: str, failure_class: str = "COMPARISON_NOT_PROVABLE") -> dict[str, Any]:
        report["status"] = "BLOCKED"
        report["failure_class"] = failure_class
        report["reason"] = reason
        return report

    if normalized_sport not in SUPPORTED_SPORTS:
        return blocked("UNSUPPORTED_SPORT", "INVALID_CONFIGURATION")
    if expected is None:
        return blocked("EXPECTED_GIT_SHA_INVALID", "INVALID_CONFIGURATION")
    report["expected_git_sha"] = expected
    if not determinism_class_value:
        return blocked("DETERMINISM_CLASS_REQUIRED", "INVALID_CONFIGURATION")
    if not replay_scope_value:
        return blocked("REPLAY_SCOPE_REQUIRED", "INVALID_CONFIGURATION")
    if not names or len(names) != len(set(names)):
        return blocked("ARTIFACT_LIST_EMPTY_OR_DUPLICATE", "INVALID_CONFIGURATION")
    if any(not _valid_artifact_name(name) for name in names):
        return blocked("ARTIFACT_PATH_INVALID", "INVALID_CONFIGURATION")
    if identity_name not in names:
        return blocked("IDENTITY_ARTIFACT_NOT_COMPARED", "INVALID_CONFIGURATION")
    if max_differences < 1:
        return blocked("MAX_DIFFERENCES_INVALID", "INVALID_CONFIGURATION")

    baseline_root = Path(baseline_dir)
    candidate_root = Path(candidate_dir)
    loaded: dict[str, tuple[Any, Any, bytes, bytes]] = {}
    for name in names:
        baseline_path = baseline_root / name
        candidate_path = candidate_root / name
        if not baseline_path.is_file():
            return blocked(f"BASELINE_ARTIFACT_MISSING:{name}", "MISSING_EVIDENCE")
        if not candidate_path.is_file():
            return blocked(f"CANDIDATE_ARTIFACT_MISSING:{name}", "MISSING_EVIDENCE")
        try:
            baseline_bytes = baseline_path.read_bytes()
        except OSError as exc:
            return blocked(f"BASELINE_ARTIFACT_READ_FAILED:{name}:{type(exc).__name__}", "MALFORMED_EVIDENCE")
        try:
            candidate_bytes = candidate_path.read_bytes()
        except OSError as exc:
            return blocked(f"CANDIDATE_ARTIFACT_READ_FAILED:{name}:{type(exc).__name__}", "MALFORMED_EVIDENCE")
        try:
            baseline_payload = _load_json_bytes(baseline_bytes)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return blocked(f"BASELINE_ARTIFACT_INVALID_JSON:{name}:{type(exc).__name__}", "MALFORMED_EVIDENCE")
        try:
            candidate_payload = _load_json_bytes(candidate_bytes)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return blocked(f"CANDIDATE_ARTIFACT_INVALID_JSON:{name}:{type(exc).__name__}", "MALFORMED_EVIDENCE")
        loaded[name] = (baseline_payload, candidate_payload, baseline_bytes, candidate_bytes)

    baseline_identity, candidate_identity, _, _ = loaded[identity_name]
    for label, payload in (("BASELINE", baseline_identity), ("CANDIDATE", candidate_identity)):
        if not isinstance(payload, dict):
            return blocked(f"{label}_IDENTITY_ARTIFACT_NOT_OBJECT", "MALFORMED_EVIDENCE")
        payload_sport = str(payload.get("sport") or "").strip().lower()
        if payload_sport and payload_sport != normalized_sport:
            return blocked(f"{label}_SPORT_MISMATCH:{payload_sport}", "IDENTITY_MISMATCH")
        code_sha = _code_git_sha(payload)
        if code_sha is None:
            return blocked(f"{label}_CODE_GIT_SHA_MISSING_OR_INVALID", "IDENTITY_MISMATCH")
        if code_sha != expected:
            return blocked(f"{label}_CODE_GIT_SHA_MISMATCH:{code_sha}", "IDENTITY_MISMATCH")

    baseline_source = _source_manifest_sha256(baseline_identity)
    candidate_source = _source_manifest_sha256(candidate_identity)
    if require_source_manifest:
        if baseline_source is None:
            return blocked("BASELINE_SOURCE_MANIFEST_SHA256_MISSING_OR_INVALID", "SOURCE_IDENTITY_MISSING")
        if candidate_source is None:
            return blocked("CANDIDATE_SOURCE_MANIFEST_SHA256_MISSING_OR_INVALID", "SOURCE_IDENTITY_MISSING")
        if baseline_source != candidate_source:
            return blocked("SOURCE_MANIFEST_SHA256_MISMATCH", "SOURCE_IDENTITY_MISMATCH")
        report["source_manifest_sha256"] = baseline_source
    elif baseline_source is not None and candidate_source is not None:
        if baseline_source != candidate_source:
            return blocked("SOURCE_MANIFEST_SHA256_MISMATCH", "SOURCE_IDENTITY_MISMATCH")
        report["source_manifest_sha256"] = baseline_source

    all_differences: list[dict[str, Any]] = []
    truncated = False
    comparisons: list[dict[str, Any]] = []
    for name in names:
        baseline_payload, candidate_payload, baseline_bytes, candidate_bytes = loaded[name]
        byte_equal = baseline_bytes == candidate_bytes
        comparison: dict[str, Any] = {
            "artifact": name,
            "baseline_byte_sha256": _bytes_sha256(baseline_bytes),
            "candidate_byte_sha256": _bytes_sha256(candidate_bytes),
            "byte_equal": byte_equal,
            "semantic_diagnostic": None,
        }

        # Semantics are diagnostic-only and are deliberately not evaluated on
        # byte-equal artifacts. They can explain a mismatch, never waive it.
        if not byte_equal:
            baseline_semantic_hash = semantic_sha256(baseline_payload)
            candidate_semantic_hash = semantic_sha256(candidate_payload)
            semantic_equal = baseline_semantic_hash == candidate_semantic_hash
            artifact_differences: list[dict[str, Any]] = []
            artifact_truncated = False
            if not semantic_equal and len(all_differences) < max_differences:
                artifact_truncated = _diff_json(
                    baseline_payload,
                    candidate_payload,
                    path="",
                    differences=artifact_differences,
                    max_differences=max_differences - len(all_differences),
                )
                for row in artifact_differences:
                    row["artifact"] = name
                all_differences.extend(artifact_differences)
            elif not semantic_equal:
                artifact_truncated = True
            comparison["semantic_diagnostic"] = {
                "baseline_semantic_sha256": baseline_semantic_hash,
                "candidate_semantic_sha256": candidate_semantic_hash,
                "semantic_equal": semantic_equal,
                "differences": artifact_differences,
                "differences_truncated": artifact_truncated,
            }
            truncated = truncated or artifact_truncated
        comparisons.append(comparison)

    report["artifact_comparisons"] = comparisons
    report["differences"] = all_differences
    report["differences_truncated"] = truncated
    all_bytes_equal = all(row["byte_equal"] for row in comparisons)
    report["all_bytes_equal"] = all_bytes_equal
    if all_bytes_equal:
        report["status"] = "PASS"
        report["failure_class"] = None
        report["reason"] = "EXACT_BYTE_OUTPUT_MATCH_AT_IDENTICAL_CODE_AND_SOURCE_IDENTITY"
    else:
        report["status"] = "FAIL"
        report["failure_class"] = "NON_DETERMINISTIC_EVIDENCE"
        report["reason"] = "BYTE_OUTPUT_MISMATCH_AT_IDENTICAL_CODE_AND_SOURCE_IDENTITY"
    return report
