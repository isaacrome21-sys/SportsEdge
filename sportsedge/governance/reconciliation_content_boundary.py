from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from sportsedge.governance.freeze_reconciliation import bundle_snapshot


DIGEST_SCHEMA = "SPORTSEDGE_GOVERNED_SURFACE_REGISTRY_DIGEST_V1"
BOUNDARY_SCHEMA = "SPORTSEDGE_RECONCILIATION_CONTENT_BOUNDARY_V1"


class ReconciliationContentBoundaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class BoundaryEvaluation:
    current_main_sha: str
    anchor_main_sha: str
    predecessor_governed_surface_digest_sha256: str
    registered_governed_surface_digest_sha256: str
    current_governed_surface_digest_sha256: str
    candidate_sha: str | None
    candidate_governed_surface_digest_sha256: str | None
    transition_mode: str
    descendant_of_anchor: bool
    one_step_merge_parentage_corroborated: bool
    release_blocks: tuple[str, ...]

    @property
    def admissible(self) -> bool:
        return not self.release_blocks

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": BOUNDARY_SCHEMA,
            "current_main_sha": self.current_main_sha,
            "anchor_main_sha": self.anchor_main_sha,
            "predecessor_governed_surface_digest_sha256": self.predecessor_governed_surface_digest_sha256,
            "registered_governed_surface_digest_sha256": self.registered_governed_surface_digest_sha256,
            "current_governed_surface_digest_sha256": self.current_governed_surface_digest_sha256,
            "candidate_sha": self.candidate_sha,
            "candidate_governed_surface_digest_sha256": self.candidate_governed_surface_digest_sha256,
            "transition_mode": self.transition_mode,
            "descendant_of_anchor": self.descendant_of_anchor,
            "one_step_merge_parentage_corroborated": self.one_step_merge_parentage_corroborated,
            "admissible": self.admissible,
            "release_blocks": list(self.release_blocks),
        }


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise ReconciliationContentBoundaryError(
            f"GIT_COMMAND_FAILED:{' '.join(args)}:{proc.returncode}:{proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _resolve_sha(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref)


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise ReconciliationContentBoundaryError(
        f"GIT_ANCESTRY_FAILED:{ancestor}:{descendant}:{proc.returncode}:{proc.stderr.strip()}"
    )


def _validate_sha256(value: object, code: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ReconciliationContentBoundaryError(code)
    return text


def validate_boundary(boundary: Mapping[str, Any]) -> None:
    if boundary.get("schema") != BOUNDARY_SCHEMA:
        raise ReconciliationContentBoundaryError("RECONCILIATION_CONTENT_BOUNDARY_SCHEMA_INVALID")
    anchor = str(boundary.get("anchor_main_sha") or "")
    if len(anchor) != 40:
        raise ReconciliationContentBoundaryError("RECONCILIATION_CONTENT_BOUNDARY_ANCHOR_INVALID")
    _validate_sha256(
        boundary.get("predecessor_governed_surface_digest_sha256"),
        "RECONCILIATION_CONTENT_BOUNDARY_PREDECESSOR_DIGEST_INVALID",
    )
    _validate_sha256(
        boundary.get("registered_governed_surface_digest_sha256"),
        "RECONCILIATION_CONTENT_BOUNDARY_REGISTERED_DIGEST_INVALID",
    )
    if any(bool(value) for value in (boundary.get("authority") or {}).values()):
        raise ReconciliationContentBoundaryError("RECONCILIATION_CONTENT_BOUNDARY_AUTHORITY_ESCALATION")
    merge = boundary.get("merge_strategy") or {}
    if merge.get("digest_primary") is not True:
        raise ReconciliationContentBoundaryError("RECONCILIATION_CONTENT_BOUNDARY_DIGEST_MUST_BE_PRIMARY")
    if merge.get("preferred_method") not in {"merge", "squash"}:
        raise ReconciliationContentBoundaryError("RECONCILIATION_CONTENT_BOUNDARY_MERGE_METHOD_INVALID")


def governed_surface_registry_payload(
    *, repo: Path, registry: Mapping[str, Any], ref: str
) -> dict[str, Any]:
    """Return content identity for the effective governed registry at ``ref``.

    Boundary/provenance bookkeeping is intentionally excluded. The payload binds
    the effective bundle definitions and every byte currently selected by those
    definitions. A commit that changes only reconciliation bookkeeping can keep
    the same identity; a coverage change, disposition change, governed file
    addition/removal, or governed file byte change changes the digest.
    """
    bundles = registry.get("bundles")
    if not isinstance(bundles, list) or not bundles:
        raise ReconciliationContentBoundaryError("GOVERNED_SURFACE_REGISTRY_BUNDLES_EMPTY")

    resolved = _resolve_sha(repo, ref)
    bundle_rows: list[dict[str, Any]] = []
    for bundle in sorted(bundles, key=lambda item: str(item.get("bundle_id") or "")):
        if not isinstance(bundle, Mapping) or not bundle.get("bundle_id"):
            raise ReconciliationContentBoundaryError("GOVERNED_SURFACE_REGISTRY_BUNDLE_INVALID")
        snapshot = bundle_snapshot(repo, bundle, resolved)
        bundle_rows.append(
            {
                "bundle_definition": dict(bundle),
                "selected_files": [list(item) for item in snapshot.files],
                "selected_files_sha256": snapshot.aggregate_sha256,
            }
        )

    excluded = {
        "issue",
        "baseline_main_sha",
        "reconciled_through_sha",
        "deltas",
        "content_boundary",
        "reconciliation_content_boundary",
        "bundles",
    }
    effective_registry_semantics = {
        str(key): value
        for key, value in registry.items()
        if str(key) not in excluded
    }
    return {
        "schema": DIGEST_SCHEMA,
        "effective_registry_semantics": effective_registry_semantics,
        "bundles": bundle_rows,
    }


def governed_surface_registry_digest(
    *, repo: Path, registry: Mapping[str, Any], ref: str
) -> str:
    return _canonical_sha256(
        governed_surface_registry_payload(repo=repo, registry=registry, ref=ref)
    )


def evaluate_content_boundary(
    *,
    repo: Path,
    registry: Mapping[str, Any],
    boundary: Mapping[str, Any],
    current_main_ref: str,
    candidate_ref: str | None = None,
) -> BoundaryEvaluation:
    validate_boundary(boundary)
    anchor = _resolve_sha(repo, str(boundary["anchor_main_sha"]))
    current = _resolve_sha(repo, current_main_ref)
    predecessor_digest = str(boundary["predecessor_governed_surface_digest_sha256"])
    registered_digest = str(boundary["registered_governed_surface_digest_sha256"])
    current_digest = governed_surface_registry_digest(
        repo=repo, registry=registry, ref=current
    )
    candidate_sha = _resolve_sha(repo, candidate_ref) if candidate_ref else None
    candidate_digest = (
        governed_surface_registry_digest(repo=repo, registry=registry, ref=candidate_sha)
        if candidate_sha
        else None
    )

    descendant = _is_ancestor(repo, anchor, current)
    blocks: list[str] = []
    transition_mode = "STABLE_REGISTERED_CONTENT"
    if not descendant:
        blocks.append(f"CURRENT_MAIN_NOT_DESCENDANT_OF_CONTENT_BOUNDARY:{anchor}:{current}")

    current_is_registered = current_digest == registered_digest
    transition_pr = (
        candidate_sha is not None
        and current == anchor
        and current_digest == predecessor_digest
        and candidate_digest == registered_digest
    )
    if current_is_registered:
        if candidate_sha is not None and candidate_digest != registered_digest:
            blocks.append(
                "CANDIDATE_GOVERNED_SURFACE_DIGEST_MISMATCH:"
                f"{registered_digest}:{candidate_digest}"
            )
    elif transition_pr:
        transition_mode = "PREMERGE_BOUNDARY_TRANSITION"
    else:
        blocks.append(
            "CURRENT_MAIN_GOVERNED_SURFACE_DIGEST_MISMATCH:"
            f"{registered_digest}:{current_digest}"
        )
        if candidate_sha is not None and candidate_digest != registered_digest:
            blocks.append(
                "CANDIDATE_GOVERNED_SURFACE_DIGEST_MISMATCH:"
                f"{registered_digest}:{candidate_digest}"
            )

    corroborated = False
    if current != anchor:
        parents = _git(repo, "rev-list", "--parents", "-n", "1", current).split()
        if len(parents) == 3 and parents[1] == anchor:
            second_parent_digest = governed_surface_registry_digest(
                repo=repo, registry=registry, ref=parents[2]
            )
            corroborated = second_parent_digest == registered_digest

    return BoundaryEvaluation(
        current_main_sha=current,
        anchor_main_sha=anchor,
        predecessor_governed_surface_digest_sha256=predecessor_digest,
        registered_governed_surface_digest_sha256=registered_digest,
        current_governed_surface_digest_sha256=current_digest,
        candidate_sha=candidate_sha,
        candidate_governed_surface_digest_sha256=candidate_digest,
        transition_mode=transition_mode,
        descendant_of_anchor=descendant,
        one_step_merge_parentage_corroborated=corroborated,
        release_blocks=tuple(sorted(set(blocks))),
    )
