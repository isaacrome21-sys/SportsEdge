from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import fnmatch
import json
import subprocess
from typing import Any, Mapping


class FreezeInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class InventoryCandidate:
    path: str
    reasons: tuple[str, ...]
    bundle_ids: tuple[str, ...]
    exemption: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "reasons": list(self.reasons),
            "bundle_ids": list(self.bundle_ids),
            "exemption": self.exemption,
        }


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise FreezeInventoryError(
            f"GIT_COMMAND_FAILED:{' '.join(args)}:{proc.returncode}:{proc.stderr.strip()}"
        )
    return proc.stdout


def _tracked_paths(repo: Path, ref: str) -> tuple[str, ...]:
    output = _git(repo, "ls-tree", "-r", "--name-only", ref)
    return tuple(sorted(line.strip() for line in output.splitlines() if line.strip()))


def _read_at_ref(repo: Path, ref: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise FreezeInventoryError(f"READ_FAILED:{ref}:{path}:{proc.returncode}")
    return proc.stdout


def _covered(path: str, bundle: Mapping[str, Any]) -> bool:
    exact = {str(value) for value in bundle.get("coverage_paths") or ()}
    prefixes = tuple(str(value) for value in bundle.get("coverage_prefixes") or ())
    return path in exact or any(path.startswith(prefix) for prefix in prefixes)


def _validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema") != "SPORTSEDGE_FREEZE_INVENTORY_POLICY_V1":
        raise FreezeInventoryError("FREEZE_INVENTORY_POLICY_SCHEMA_INVALID")
    exemptions = policy.get("exact_exemptions")
    if not isinstance(exemptions, Mapping):
        raise FreezeInventoryError("FREEZE_INVENTORY_EXEMPTIONS_INVALID")
    for path, reason in exemptions.items():
        if not isinstance(path, str) or not path or not isinstance(reason, str) or not reason:
            raise FreezeInventoryError("FREEZE_INVENTORY_EXEMPTION_INVALID")
        if any(token in path for token in ("*", "?", "[", "]")):
            raise FreezeInventoryError(f"FREEZE_INVENTORY_WILDCARD_EXEMPTION_FORBIDDEN:{path}")
    authority = policy.get("authority") or {}
    if any(bool(value) for value in authority.values()):
        raise FreezeInventoryError("FREEZE_INVENTORY_AUTHORITY_ESCALATION_FORBIDDEN")


def _candidate_reasons(path: str, text: str, policy: Mapping[str, Any]) -> tuple[str, ...]:
    roots = tuple(str(v) for v in policy.get("candidate_roots") or ())
    if not any(path.startswith(root) for root in roots):
        return ()
    reasons: list[str] = []
    lower = path.lower()
    for token in policy.get("candidate_path_tokens") or ():
        token_s = str(token).lower()
        if token_s in lower:
            reasons.append(f"PATH_TOKEN:{token_s}")
    suffixes = tuple(str(v) for v in policy.get("content_scan_suffixes") or ())
    if path.endswith(suffixes):
        for marker in policy.get("content_markers") or ():
            marker_s = str(marker)
            if marker_s in text:
                reasons.append(f"CONTENT_MARKER:{marker_s}")
    return tuple(sorted(set(reasons)))


def audit_inventory(
    *,
    repo: Path,
    ref: str,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_policy(policy)
    bundles = registry.get("bundles")
    if not isinstance(bundles, list) or not bundles:
        raise FreezeInventoryError("FREEZE_INVENTORY_BUNDLES_EMPTY")
    exemptions = {str(k): str(v) for k, v in (policy.get("exact_exemptions") or {}).items()}
    candidates: list[InventoryCandidate] = []
    for path in _tracked_paths(repo, ref):
        suffixes = tuple(str(v) for v in policy.get("content_scan_suffixes") or ())
        text = _read_at_ref(repo, ref, path) if path.endswith(suffixes) else ""
        reasons = _candidate_reasons(path, text, policy)
        if not reasons:
            continue
        mapped = tuple(sorted(str(b["bundle_id"]) for b in bundles if _covered(path, b)))
        exemption = exemptions.get(path)
        candidates.append(
            InventoryCandidate(
                path=path,
                reasons=reasons,
                bundle_ids=mapped,
                exemption=exemption,
            )
        )

    tracked = set(_tracked_paths(repo, ref))
    stale_exemptions = sorted(path for path in exemptions if path not in tracked)
    unmapped = sorted(
        c.path for c in candidates if not c.bundle_ids and c.exemption is None
    )
    multiply_mapped = sorted(c.path for c in candidates if len(c.bundle_ids) > 1)
    complete = not unmapped and not stale_exemptions
    claimed = bool(registry.get("bundle_inventory_complete"))
    claim_matches = claimed == complete
    blocks: list[str] = []
    if unmapped:
        blocks.append("UNMAPPED_GOVERNANCE_SURFACES")
    if stale_exemptions:
        blocks.append("STALE_EXACT_EXEMPTIONS")
    if not claim_matches:
        blocks.append("REGISTRY_INVENTORY_COMPLETENESS_CLAIM_MISMATCH")
    return {
        "schema": "SPORTSEDGE_FREEZE_INVENTORY_AUDIT_V1",
        "ref": ref,
        "candidate_count": len(candidates),
        "candidates": [c.as_dict() for c in candidates],
        "unmapped_paths": unmapped,
        "stale_exemptions": stale_exemptions,
        "multiply_mapped_paths": multiply_mapped,
        "computed_complete": complete,
        "registry_claimed_complete": claimed,
        "claim_matches_computation": claim_matches,
        "release_blocks": blocks,
        "authority": dict(policy.get("authority") or {}),
    }


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
