"""Historical Git provenance verification for frozen Truth Gate edge floors.

This module is a freeze/CI boundary, not a betting-runtime dependency.  A frozen
floor may be accepted only when the pre-analysis manifest, derivation code, and
result evidence can be reconstructed from the commits recorded in the floor
record and their ancestry proves the required chronology.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .edge_floors import FloorStatus, load_edge_floor_config, require_frozen_edge_floor


class FloorProvenanceError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedFloorProvenance:
    market: str
    manifest_commit: str
    evidence_commit: str
    derivation_code_commit: str
    floor_commit: str
    manifest_sha256: str
    evidence_sha256: str
    derivation_code_sha256: str


def _invalid(reason: str) -> FloorProvenanceError:
    return FloorProvenanceError(f"PROVENANCE_INVALID:{reason}")


def _unresolvable(reason: str) -> FloorProvenanceError:
    return FloorProvenanceError(f"PROVENANCE_UNRESOLVABLE:{reason}")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise _invalid(f"{field}_MALFORMED")
    return text


def _require_commit(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise _invalid(f"{field}_MALFORMED")
    return text


def _require_repo_path(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    path = Path(text)
    if (
        not text
        or path.is_absolute()
        or ".." in path.parts
        or text.startswith("./")
        or "\\" in text
    ):
        raise _invalid(f"{field}_INVALID")
    return path.as_posix()


def _git(repo_root: Path, *args: str, capture_bytes: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=not capture_bytes,
            check=False,
        )
    except OSError as exc:
        raise _unresolvable("GIT_EXECUTION_FAILED") from exc


def _commit_exists(repo_root: Path, commit: str, *, field: str) -> None:
    proc = _git(repo_root, "cat-file", "-e", f"{commit}^{{commit}}")
    if proc.returncode != 0:
        raise _unresolvable(f"{field}_COMMIT_NOT_AVAILABLE")


def _historical_bytes(repo_root: Path, *, commit: str, path: str, field: str) -> bytes:
    _commit_exists(repo_root, commit, field=field)
    proc = _git(repo_root, "show", f"{commit}:{path}", capture_bytes=True)
    if proc.returncode != 0:
        raise _unresolvable(f"{field}_PATH_NOT_AVAILABLE_AT_COMMIT")
    return bytes(proc.stdout)


def _require_strict_ancestor(
    repo_root: Path, *, ancestor: str, descendant: str, relation: str
) -> None:
    if ancestor == descendant:
        raise _invalid(f"{relation}_NOT_STRICT")
    _commit_exists(repo_root, ancestor, field=f"{relation}_ANCESTOR")
    _commit_exists(repo_root, descendant, field=f"{relation}_DESCENDANT")
    proc = _git(repo_root, "merge-base", "--is-ancestor", ancestor, descendant)
    if proc.returncode == 0:
        return
    if proc.returncode == 1:
        raise _invalid(f"{relation}_ANCESTRY_MISMATCH")
    # Exit codes other than 0/1 indicate the relation could not be resolved,
    # which is materially different from a resolved-but-invalid ancestry.  A
    # shallow checkout is a common cause; provenance CI therefore uses depth 0.
    raise _unresolvable(f"{relation}_ANCESTRY_CHECK_FAILED")


def verify_floor_provenance(
    *, market: str, config: Mapping[str, Any], repo_root: str | Path = "."
) -> VerifiedFloorProvenance:
    """Verify one frozen floor against historical file bytes and strict ancestry."""
    root = Path(repo_root).resolve()
    if not (root / ".git").exists():
        # Worktrees may use a .git file, so exists() is intentional rather than
        # is_dir().
        raise _unresolvable("GIT_REPOSITORY_REQUIRED")

    floor = require_frozen_edge_floor(market=market, config=config)
    truth_gate = config.get("truth_gate")
    floors = truth_gate.get("edge_floors") if isinstance(truth_gate, Mapping) else None
    record = floors.get(market) if isinstance(floors, Mapping) else None
    if not isinstance(record, Mapping):
        raise _invalid("FLOOR_RECORD_REQUIRED")
    evidence = record.get("evidence")
    frozen = record.get("frozen")
    if not isinstance(evidence, Mapping) or not isinstance(frozen, Mapping):
        raise _invalid("FLOOR_PROVENANCE_METADATA_REQUIRED")

    manifest_commit = _require_commit(evidence.get("manifest_commit"), field="manifest_commit")
    evidence_commit = _require_commit(evidence.get("evidence_commit"), field="evidence_commit")
    derivation_code_commit = _require_commit(
        evidence.get("derivation_code_commit"), field="derivation_code_commit"
    )
    floor_commit = _require_commit(frozen.get("frozen_by_commit"), field="frozen_by_commit")

    manifest_path = _require_repo_path(evidence.get("manifest_path"), field="manifest_path")
    evidence_path = _require_repo_path(evidence.get("evidence_path"), field="evidence_path")
    derivation_code_path = _require_repo_path(
        evidence.get("derivation_code_path"), field="derivation_code_path"
    )

    manifest_sha = _require_sha(evidence.get("manifest_sha256"), field="manifest_sha256")
    evidence_sha = _require_sha(floor.evidence_sha256, field="evidence_sha256")
    derivation_sha = _require_sha(
        floor.derivation_code_sha256, field="derivation_code_sha256"
    )

    _require_strict_ancestor(
        root,
        ancestor=manifest_commit,
        descendant=evidence_commit,
        relation="MANIFEST_BEFORE_EVIDENCE",
    )
    _require_strict_ancestor(
        root,
        ancestor=derivation_code_commit,
        descendant=evidence_commit,
        relation="DERIVATION_CODE_BEFORE_EVIDENCE",
    )
    _require_strict_ancestor(
        root,
        ancestor=evidence_commit,
        descendant=floor_commit,
        relation="EVIDENCE_BEFORE_FLOOR_FREEZE",
    )

    actual_manifest_sha = _sha256(
        _historical_bytes(
            root, commit=manifest_commit, path=manifest_path, field="MANIFEST"
        )
    )
    if actual_manifest_sha != manifest_sha:
        raise _invalid("MANIFEST_SHA256_MISMATCH")

    actual_evidence_sha = _sha256(
        _historical_bytes(
            root, commit=evidence_commit, path=evidence_path, field="EVIDENCE"
        )
    )
    if actual_evidence_sha != evidence_sha:
        raise _invalid("EVIDENCE_SHA256_MISMATCH")

    actual_derivation_sha = _sha256(
        _historical_bytes(
            root,
            commit=derivation_code_commit,
            path=derivation_code_path,
            field="DERIVATION_CODE",
        )
    )
    if actual_derivation_sha != derivation_sha:
        raise _invalid("DERIVATION_CODE_SHA256_MISMATCH")

    return VerifiedFloorProvenance(
        market=market,
        manifest_commit=manifest_commit,
        evidence_commit=evidence_commit,
        derivation_code_commit=derivation_code_commit,
        floor_commit=floor_commit,
        manifest_sha256=manifest_sha,
        evidence_sha256=evidence_sha,
        derivation_code_sha256=derivation_sha,
    )


def verify_floor_config_provenance(
    *, config_path: str | Path, repo_root: str | Path = "."
) -> list[VerifiedFloorProvenance]:
    """Verify every FROZEN floor in a config; zero frozen floors is a valid no-promotion state."""
    config = load_edge_floor_config(str(config_path))
    truth_gate = config.get("truth_gate")
    floors = truth_gate.get("edge_floors") if isinstance(truth_gate, Mapping) else None
    if not isinstance(floors, Mapping):
        raise _invalid("EDGE_FLOORS_MAPPING_REQUIRED")
    verified: list[VerifiedFloorProvenance] = []
    for market, record in sorted(floors.items()):
        if isinstance(record, Mapping) and record.get("status") == FloorStatus.FROZEN.value:
            verified.append(
                verify_floor_provenance(
                    market=str(market), config=config, repo_root=repo_root
                )
            )
    return verified


def report_verified(values: list[VerifiedFloorProvenance]) -> str:
    return json.dumps(
        {
            "schema": "TRUTH_GATE_FLOOR_PROVENANCE_V1",
            "status": "PASS",
            "frozen_floor_count": len(values),
            "markets": [value.market for value in values],
        },
        sort_keys=True,
    )
