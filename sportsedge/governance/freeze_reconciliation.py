from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

MATRIX_OUTCOMES = frozenset(
    {"MATCH", "PROVISIONAL_DRIFT_BLOCKED", "NOT_APPLICABLE", "DRIFT_CONFIRMED"}
)
TERMINAL_MATRIX_OUTCOMES = frozenset({"MATCH", "NOT_APPLICABLE", "DRIFT_CONFIRMED"})
DRIFT_DISPOSITIONS = frozenset({"REFROZEN", "REVOKED"})


class FreezeReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BundleSnapshot:
    commit_sha: str
    files: tuple[tuple[str, str], ...]
    aggregate_sha256: str


@dataclass(frozen=True)
class MatrixRow:
    delta_id: str
    pr: int
    merge_sha: str
    parent_sha: str
    bundle_id: str
    bundle_freeze_sha: str
    outcome: str
    reason: str
    changed_paths: tuple[str, ...]
    covered_changed_paths: tuple[str, ...]
    before_bundle_sha256: str | None
    after_bundle_sha256: str | None
    delta_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "delta_id": self.delta_id,
            "pr": self.pr,
            "merge_sha": self.merge_sha,
            "parent_sha": self.parent_sha,
            "bundle_id": self.bundle_id,
            "bundle_freeze_sha": self.bundle_freeze_sha,
            "outcome": self.outcome,
            "reason": self.reason,
            "changed_paths": list(self.changed_paths),
            "covered_changed_paths": list(self.covered_changed_paths),
            "before_bundle_sha256": self.before_bundle_sha256,
            "after_bundle_sha256": self.after_bundle_sha256,
            "delta_sha256": self.delta_sha256,
        }


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _git(repo: Path, *args: str, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=text,
    )
    if check and proc.returncode != 0:
        stderr = proc.stderr.strip() if text else proc.stderr.decode("utf-8", "replace")
        raise FreezeReconciliationError(
            f"GIT_COMMAND_FAILED:{' '.join(args)}:{proc.returncode}:{stderr}"
        )
    return proc


def resolve_sha(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def first_parent(repo: Path, commit_sha: str) -> str:
    return resolve_sha(repo, f"{commit_sha}^1")


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    proc = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise FreezeReconciliationError(
        f"GIT_ANCESTRY_FAILED:{ancestor}:{descendant}:{proc.returncode}:{proc.stderr.strip()}"
    )


def changed_paths(repo: Path, parent_sha: str, merge_sha: str) -> tuple[str, ...]:
    output = _git(repo, "diff", "--name-only", parent_sha, merge_sha, "--").stdout
    return tuple(sorted({line.strip() for line in output.splitlines() if line.strip()}))


def _covered(path: str, bundle: Mapping[str, Any]) -> bool:
    exact = {str(value) for value in bundle.get("coverage_paths") or ()}
    prefixes = tuple(str(value) for value in bundle.get("coverage_prefixes") or ())
    return path in exact or any(path.startswith(prefix) for prefix in prefixes)


def _tree_paths(repo: Path, commit_sha: str) -> tuple[str, ...]:
    output = _git(repo, "ls-tree", "-r", "--name-only", commit_sha).stdout
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def _blob_bytes(repo: Path, commit_sha: str, path: str) -> bytes:
    proc = _git(repo, "show", f"{commit_sha}:{path}", text=False)
    return bytes(proc.stdout)


def bundle_snapshot(repo: Path, bundle: Mapping[str, Any], commit_sha: str) -> BundleSnapshot:
    files: list[tuple[str, str]] = []
    for path in _tree_paths(repo, commit_sha):
        if not _covered(path, bundle):
            continue
        files.append((path, sha256(_blob_bytes(repo, commit_sha, path)).hexdigest()))
    files.sort()
    aggregate = _canonical_sha256(
        {"bundle_id": bundle["bundle_id"], "files": files}
    )
    return BundleSnapshot(commit_sha=commit_sha, files=tuple(files), aggregate_sha256=aggregate)


def _delta_sha(
    *, merge_sha: str, parent_sha: str, paths: Iterable[str]
) -> str:
    return _canonical_sha256(
        {
            "merge_sha": merge_sha,
            "parent_sha": parent_sha,
            "changed_paths": tuple(sorted(paths)),
        }
    )


def reconcile_delta_bundle(
    repo: Path,
    delta: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> MatrixRow:
    delta_id = str(delta["delta_id"])
    pr = int(delta["pr"])
    merge_sha = resolve_sha(repo, str(delta["merge_sha"]))
    freeze_sha = resolve_sha(repo, str(bundle["freeze_sha"]))
    bundle_id = str(bundle["bundle_id"])
    try:
        parent_sha = first_parent(repo, merge_sha)
        paths = changed_paths(repo, parent_sha, merge_sha)
    except FreezeReconciliationError as exc:
        return MatrixRow(
            delta_id=delta_id,
            pr=pr,
            merge_sha=merge_sha,
            parent_sha="UNRESOLVED",
            bundle_id=bundle_id,
            bundle_freeze_sha=freeze_sha,
            outcome="PROVISIONAL_DRIFT_BLOCKED",
            reason=f"DELTA_PROVENANCE_UNRESOLVED:{exc}",
            changed_paths=(),
            covered_changed_paths=(),
            before_bundle_sha256=None,
            after_bundle_sha256=None,
            delta_sha256=_canonical_sha256({"merge_sha": merge_sha, "error": str(exc)}),
        )

    identity = _delta_sha(merge_sha=merge_sha, parent_sha=parent_sha, paths=paths)

    # If the delta was already present at the bundle's frozen commit, it cannot be
    # a post-freeze drift event for that bundle. This is temporal irrelevance, not
    # a semantic classification.
    if merge_sha == freeze_sha or is_ancestor(repo, merge_sha, freeze_sha):
        return MatrixRow(
            delta_id=delta_id,
            pr=pr,
            merge_sha=merge_sha,
            parent_sha=parent_sha,
            bundle_id=bundle_id,
            bundle_freeze_sha=freeze_sha,
            outcome="NOT_APPLICABLE",
            reason="DELTA_ALREADY_INCLUDED_IN_BUNDLE_FREEZE",
            changed_paths=paths,
            covered_changed_paths=(),
            before_bundle_sha256=None,
            after_bundle_sha256=None,
            delta_sha256=identity,
        )

    covered = tuple(path for path in paths if _covered(path, bundle))
    if not covered:
        return MatrixRow(
            delta_id=delta_id,
            pr=pr,
            merge_sha=merge_sha,
            parent_sha=parent_sha,
            bundle_id=bundle_id,
            bundle_freeze_sha=freeze_sha,
            outcome="NOT_APPLICABLE",
            reason="NO_COVERED_PATH_INTERSECTION",
            changed_paths=paths,
            covered_changed_paths=(),
            before_bundle_sha256=None,
            after_bundle_sha256=None,
            delta_sha256=identity,
        )

    try:
        before = bundle_snapshot(repo, bundle, parent_sha)
        after = bundle_snapshot(repo, bundle, merge_sha)
    except FreezeReconciliationError as exc:
        return MatrixRow(
            delta_id=delta_id,
            pr=pr,
            merge_sha=merge_sha,
            parent_sha=parent_sha,
            bundle_id=bundle_id,
            bundle_freeze_sha=freeze_sha,
            outcome="PROVISIONAL_DRIFT_BLOCKED",
            reason=f"BUNDLE_REPLAY_UNRESOLVED:{exc}",
            changed_paths=paths,
            covered_changed_paths=covered,
            before_bundle_sha256=None,
            after_bundle_sha256=None,
            delta_sha256=identity,
        )

    if before.aggregate_sha256 == after.aggregate_sha256:
        outcome = "MATCH"
        reason = "COVERED_BUNDLE_BYTES_AND_INVENTORY_UNCHANGED"
    else:
        outcome = "DRIFT_CONFIRMED"
        reason = "COVERED_BUNDLE_BYTES_OR_INVENTORY_CHANGED"
    return MatrixRow(
        delta_id=delta_id,
        pr=pr,
        merge_sha=merge_sha,
        parent_sha=parent_sha,
        bundle_id=bundle_id,
        bundle_freeze_sha=freeze_sha,
        outcome=outcome,
        reason=reason,
        changed_paths=paths,
        covered_changed_paths=covered,
        before_bundle_sha256=before.aggregate_sha256,
        after_bundle_sha256=after.aggregate_sha256,
        delta_sha256=identity,
    )


def reconcile_freeze_to_baseline(
    repo: Path,
    *,
    baseline_main_sha: str,
    bundle: Mapping[str, Any],
) -> MatrixRow:
    """Reconcile all bundle drift from its freeze through the hold baseline.

    The delta matrix only observes commits explicitly registered after the hold
    baseline. Active bundles may have frozen earlier, so freeze-to-baseline drift
    must be adjudicated independently or pre-hold semantic changes can disappear
    from the reconciliation record.
    """

    freeze_sha = resolve_sha(repo, str(bundle["freeze_sha"]))
    baseline_sha = resolve_sha(repo, baseline_main_sha)
    bundle_id = str(bundle["bundle_id"])
    delta_id = "PREHOLD_BASELINE"

    if freeze_sha == baseline_sha:
        return MatrixRow(
            delta_id=delta_id,
            pr=0,
            merge_sha=baseline_sha,
            parent_sha=freeze_sha,
            bundle_id=bundle_id,
            bundle_freeze_sha=freeze_sha,
            outcome="NOT_APPLICABLE",
            reason="BUNDLE_FREEZE_EQUALS_HOLD_BASELINE",
            changed_paths=(),
            covered_changed_paths=(),
            before_bundle_sha256=None,
            after_bundle_sha256=None,
            delta_sha256=_delta_sha(merge_sha=baseline_sha, parent_sha=freeze_sha, paths=()),
        )

    try:
        if is_ancestor(repo, baseline_sha, freeze_sha):
            return MatrixRow(
                delta_id=delta_id,
                pr=0,
                merge_sha=baseline_sha,
                parent_sha=freeze_sha,
                bundle_id=bundle_id,
                bundle_freeze_sha=freeze_sha,
                outcome="NOT_APPLICABLE",
                reason="BUNDLE_FREEZE_POSTDATES_HOLD_BASELINE",
                changed_paths=(),
                covered_changed_paths=(),
                before_bundle_sha256=None,
                after_bundle_sha256=None,
                delta_sha256=_delta_sha(
                    merge_sha=baseline_sha, parent_sha=freeze_sha, paths=()
                ),
            )
        if not is_ancestor(repo, freeze_sha, baseline_sha):
            return MatrixRow(
                delta_id=delta_id,
                pr=0,
                merge_sha=baseline_sha,
                parent_sha=freeze_sha,
                bundle_id=bundle_id,
                bundle_freeze_sha=freeze_sha,
                outcome="PROVISIONAL_DRIFT_BLOCKED",
                reason="FREEZE_TO_HOLD_BASELINE_ANCESTRY_DIVERGED",
                changed_paths=(),
                covered_changed_paths=(),
                before_bundle_sha256=None,
                after_bundle_sha256=None,
                delta_sha256=_canonical_sha256(
                    {
                        "freeze_sha": freeze_sha,
                        "baseline_sha": baseline_sha,
                        "bundle_id": bundle_id,
                        "reason": "ANCESTRY_DIVERGED",
                    }
                ),
            )
        paths = changed_paths(repo, freeze_sha, baseline_sha)
        covered = tuple(path for path in paths if _covered(path, bundle))
        identity = _delta_sha(
            merge_sha=baseline_sha, parent_sha=freeze_sha, paths=paths
        )
        if not covered:
            return MatrixRow(
                delta_id=delta_id,
                pr=0,
                merge_sha=baseline_sha,
                parent_sha=freeze_sha,
                bundle_id=bundle_id,
                bundle_freeze_sha=freeze_sha,
                outcome="NOT_APPLICABLE",
                reason="NO_COVERED_PATH_CHANGE_FREEZE_TO_HOLD_BASELINE",
                changed_paths=paths,
                covered_changed_paths=(),
                before_bundle_sha256=None,
                after_bundle_sha256=None,
                delta_sha256=identity,
            )
        before = bundle_snapshot(repo, bundle, freeze_sha)
        after = bundle_snapshot(repo, bundle, baseline_sha)
    except FreezeReconciliationError as exc:
        return MatrixRow(
            delta_id=delta_id,
            pr=0,
            merge_sha=baseline_sha,
            parent_sha=freeze_sha,
            bundle_id=bundle_id,
            bundle_freeze_sha=freeze_sha,
            outcome="PROVISIONAL_DRIFT_BLOCKED",
            reason=f"FREEZE_TO_HOLD_BASELINE_REPLAY_UNRESOLVED:{exc}",
            changed_paths=(),
            covered_changed_paths=(),
            before_bundle_sha256=None,
            after_bundle_sha256=None,
            delta_sha256=_canonical_sha256(
                {
                    "freeze_sha": freeze_sha,
                    "baseline_sha": baseline_sha,
                    "bundle_id": bundle_id,
                    "error": str(exc),
                }
            ),
        )

    if before.aggregate_sha256 == after.aggregate_sha256:
        outcome = "MATCH"
        reason = "COVERED_BUNDLE_MATCHES_FREEZE_AT_HOLD_BASELINE"
    else:
        outcome = "DRIFT_CONFIRMED"
        reason = "COVERED_BUNDLE_DRIFT_BEFORE_HOLD_BASELINE"
    return MatrixRow(
        delta_id=delta_id,
        pr=0,
        merge_sha=baseline_sha,
        parent_sha=freeze_sha,
        bundle_id=bundle_id,
        bundle_freeze_sha=freeze_sha,
        outcome=outcome,
        reason=reason,
        changed_paths=paths,
        covered_changed_paths=covered,
        before_bundle_sha256=before.aggregate_sha256,
        after_bundle_sha256=after.aggregate_sha256,
        delta_sha256=identity,
    )


def _validate_registry(policy: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    if policy.get("schema") != "SPORTSEDGE_FREEZE_RECONCILIATION_POLICY_V1":
        raise FreezeReconciliationError("FREEZE_RECONCILIATION_POLICY_SCHEMA_INVALID")
    if registry.get("schema") != "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1":
        raise FreezeReconciliationError("FREEZE_RECONCILIATION_REGISTRY_SCHEMA_INVALID")
    if policy.get("main_merge_hold") != "UNCONDITIONAL":
        raise FreezeReconciliationError("FREEZE_MAIN_HOLD_MUST_BE_UNCONDITIONAL")
    if policy.get("status") not in {"ACTIVE_BLOCKED", "RESOLVED"}:
        raise FreezeReconciliationError("FREEZE_POLICY_STATUS_INVALID")
    if not registry.get("baseline_main_sha"):
        raise FreezeReconciliationError("FREEZE_RECONCILIATION_BASELINE_MAIN_SHA_MISSING")
    deltas = registry.get("deltas")
    bundles = registry.get("bundles")
    if not isinstance(deltas, list) or not deltas:
        raise FreezeReconciliationError("FREEZE_RECONCILIATION_DELTAS_EMPTY")
    if not isinstance(bundles, list) or not bundles:
        raise FreezeReconciliationError("FREEZE_RECONCILIATION_BUNDLES_EMPTY")
    delta_ids = [str(row.get("delta_id")) for row in deltas]
    if len(delta_ids) != len(set(delta_ids)):
        raise FreezeReconciliationError("FREEZE_RECONCILIATION_DELTA_ID_DUPLICATE")
    bundle_ids = [str(row.get("bundle_id")) for row in bundles]
    if len(bundle_ids) != len(set(bundle_ids)):
        raise FreezeReconciliationError("FREEZE_RECONCILIATION_BUNDLE_ID_DUPLICATE")
    for bundle in bundles:
        if not bundle.get("freeze_sha"):
            raise FreezeReconciliationError(
                f"FREEZE_RECONCILIATION_BUNDLE_FREEZE_SHA_MISSING:{bundle.get('bundle_id')}"
            )
        if not (bundle.get("coverage_paths") or bundle.get("coverage_prefixes")):
            raise FreezeReconciliationError(
                f"FREEZE_RECONCILIATION_BUNDLE_COVERAGE_EMPTY:{bundle.get('bundle_id')}"
            )
        disposition = bundle.get("disposition")
        if disposition is not None and disposition.get("state") not in DRIFT_DISPOSITIONS:
            raise FreezeReconciliationError(
                f"FREEZE_RECONCILIATION_DISPOSITION_INVALID:{bundle.get('bundle_id')}"
            )


def _bundle_resolution_blocks(
    repo: Path, bundle: Mapping[str, Any], rows: Iterable[MatrixRow]
) -> tuple[str, ...]:
    drifted = any(row.outcome == "DRIFT_CONFIRMED" for row in rows)
    if not drifted:
        return ()
    disposition = bundle.get("disposition")
    bundle_id = str(bundle["bundle_id"])
    if not isinstance(disposition, Mapping):
        return (f"DRIFT_DISPOSITION_REQUIRED:{bundle_id}",)
    state = str(disposition.get("state") or "")
    if state == "REFROZEN":
        required = (
            "new_bundle_id",
            "new_freeze_sha",
            "forward_clock_restart_at",
        )
        missing = [key for key in required if not disposition.get(key)]
        if missing:
            return (f"REFREEZE_FIELDS_MISSING:{bundle_id}:{','.join(missing)}",)
        try:
            new_sha = resolve_sha(repo, str(disposition["new_freeze_sha"]))
            old_sha = resolve_sha(repo, str(bundle["freeze_sha"]))
            if not is_ancestor(repo, old_sha, new_sha):
                return (f"REFREEZE_NOT_DESCENDANT:{bundle_id}",)
        except FreezeReconciliationError:
            return (f"REFREEZE_SHA_UNRESOLVED:{bundle_id}",)
        return ()
    if state == "REVOKED":
        if not disposition.get("revoked_at"):
            return (f"REVOCATION_TIMESTAMP_MISSING:{bundle_id}",)
        if disposition.get("prior_forward_clock_invalidated") is not True:
            return (f"REVOCATION_CLOCK_INVALIDATION_REQUIRED:{bundle_id}",)
        return ()
    return (f"DRIFT_DISPOSITION_INVALID:{bundle_id}:{state}",)


def build_reconciliation_report(
    *,
    repo: Path,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    current_main_ref: str,
) -> dict[str, Any]:
    _validate_registry(policy, registry)
    current_main_sha = resolve_sha(repo, current_main_ref)
    baseline_main_sha = resolve_sha(repo, str(registry["baseline_main_sha"]))
    rows: list[MatrixRow] = []
    rows_by_bundle: dict[str, list[MatrixRow]] = {
        str(bundle["bundle_id"]): [] for bundle in registry["bundles"]
    }

    for bundle in registry["bundles"]:
        row = reconcile_freeze_to_baseline(
            repo,
            baseline_main_sha=baseline_main_sha,
            bundle=bundle,
        )
        if row.outcome not in MATRIX_OUTCOMES:
            raise FreezeReconciliationError(
                f"FREEZE_RECONCILIATION_OUTCOME_INVALID:{row.outcome}"
            )
        rows.append(row)
        rows_by_bundle[row.bundle_id].append(row)

    for delta in registry["deltas"]:
        for bundle in registry["bundles"]:
            row = reconcile_delta_bundle(repo, delta, bundle)
            if row.outcome not in MATRIX_OUTCOMES:
                raise FreezeReconciliationError(
                    f"FREEZE_RECONCILIATION_OUTCOME_INVALID:{row.outcome}"
                )
            rows.append(row)
            rows_by_bundle[row.bundle_id].append(row)

    blocks: list[str] = []
    if not registry.get("bundle_inventory_complete"):
        blocks.append("ACTIVE_FREEZE_BUNDLE_INVENTORY_INCOMPLETE")
    if any(row.outcome == "PROVISIONAL_DRIFT_BLOCKED" for row in rows):
        blocks.append("PROVISIONAL_DRIFT_ROWS_REMAIN")
    for bundle in registry["bundles"]:
        blocks.extend(
            _bundle_resolution_blocks(
                repo, bundle, rows_by_bundle[str(bundle["bundle_id"])]
            )
        )
    reconciled_through = resolve_sha(repo, str(registry["reconciled_through_sha"]))
    if current_main_sha != reconciled_through:
        blocks.append(
            f"MAIN_ADVANCED_BEYOND_RECONCILIATION:{reconciled_through}:{current_main_sha}"
        )

    outcome_counts = {name: 0 for name in sorted(MATRIX_OUTCOMES)}
    for row in rows:
        outcome_counts[row.outcome] += 1
    release_ready = not blocks
    return {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REPORT_V1",
        "issue": int(policy["issue"]),
        "policy_status": policy["status"],
        "main_merge_hold": policy["main_merge_hold"],
        "current_main_sha": current_main_sha,
        "baseline_main_sha": baseline_main_sha,
        "reconciled_through_sha": reconciled_through,
        "bundle_inventory_complete": bool(registry.get("bundle_inventory_complete")),
        "matrix_row_count": len(rows),
        "outcome_counts": outcome_counts,
        "rows": [row.as_dict() for row in rows],
        "release_ready": release_ready,
        "release_blocks": sorted(set(blocks)),
        "authority": dict(policy.get("authority") or {}),
        "report_sha256": _canonical_sha256(
            {
                "current_main_sha": current_main_sha,
                "baseline_main_sha": baseline_main_sha,
                "reconciled_through_sha": reconciled_through,
                "rows": [row.as_dict() for row in rows],
                "blocks": sorted(set(blocks)),
            }
        ),
    }


def load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FreezeReconciliationError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload
