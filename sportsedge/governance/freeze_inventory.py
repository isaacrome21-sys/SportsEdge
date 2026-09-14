from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
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


def _scanner_contract_payload(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_roots": list(policy.get("candidate_roots") or ()),
        "candidate_path_tokens": list(policy.get("candidate_path_tokens") or ()),
        "content_scan_suffixes": list(policy.get("content_scan_suffixes") or ()),
        "content_markers": list(policy.get("content_markers") or ()),
        "rules": dict(policy.get("rules") or {}),
    }


def _scanner_contract_sha256(policy: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _scanner_contract_payload(policy), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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

    scanner = policy.get("scanner_contract")
    if scanner is not None:
        if not isinstance(scanner, Mapping):
            raise FreezeInventoryError("FREEZE_INVENTORY_SCANNER_CONTRACT_INVALID")
        expected = str(scanner.get("canonical_json_sha256") or "")
        actual = _scanner_contract_sha256(policy)
        if expected != actual:
            raise FreezeInventoryError(
                f"FREEZE_INVENTORY_SCANNER_CONTRACT_DRIFT:{expected}:{actual}"
            )
        floor = scanner.get("candidate_total_floor")
        if not isinstance(floor, int) or floor < 1:
            raise FreezeInventoryError("FREEZE_INVENTORY_CANDIDATE_FLOOR_INVALID")

    convergence = policy.get("inventory_convergence")
    if convergence is not None:
        if not isinstance(convergence, Mapping):
            raise FreezeInventoryError("FREEZE_INVENTORY_CONVERGENCE_POLICY_INVALID")
        window = convergence.get("stall_window_transitions")
        if not isinstance(window, int) or window < 1:
            raise FreezeInventoryError("FREEZE_INVENTORY_STALL_WINDOW_INVALID")
        passes = convergence.get("completed_passes")
        if not isinstance(passes, list) or not passes:
            raise FreezeInventoryError("FREEZE_INVENTORY_PASS_HISTORY_EMPTY")
        seen_heads: set[str] = set()
        for entry in passes:
            if not isinstance(entry, Mapping):
                raise FreezeInventoryError("FREEZE_INVENTORY_PASS_HISTORY_INVALID")
            head = str(entry.get("head_sha") or "")
            if len(head) != 40 or head in seen_heads:
                raise FreezeInventoryError("FREEZE_INVENTORY_PASS_HEAD_INVALID")
            seen_heads.add(head)
            for key in ("candidate_count", "mapped_or_exactly_exempt_count", "unmapped_count"):
                if not isinstance(entry.get(key), int) or int(entry[key]) < 0:
                    raise FreezeInventoryError("FREEZE_INVENTORY_PASS_COUNT_INVALID")
            if int(entry["mapped_or_exactly_exempt_count"]) + int(entry["unmapped_count"]) != int(entry["candidate_count"]):
                raise FreezeInventoryError("FREEZE_INVENTORY_PASS_ACCOUNTING_INVALID")


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


def _convergence_state(
    *,
    repo: Path,
    ref: str,
    policy: Mapping[str, Any],
    candidate_count: int,
    unmapped_count: int,
) -> dict[str, Any]:
    convergence = policy.get("inventory_convergence") or {}
    if not convergence:
        return {
            "status": "NOT_CONFIGURED",
            "distinct_head_transition_count": 0,
            "consecutive_non_decreasing_unmapped_transitions": 0,
            "outcome": None,
        }

    history = [dict(item) for item in convergence.get("completed_passes") or ()]
    current_head = _git(repo, "rev-parse", ref).strip()
    if not history or history[-1].get("head_sha") != current_head:
        history.append(
            {
                "pass_id": "LIVE_AUDIT",
                "head_sha": current_head,
                "candidate_count": candidate_count,
                "mapped_or_exactly_exempt_count": candidate_count - unmapped_count,
                "unmapped_count": unmapped_count,
            }
        )

    non_decreasing_flags: list[bool] = []
    for prior, current in zip(history, history[1:]):
        non_decreasing_flags.append(int(current["unmapped_count"]) >= int(prior["unmapped_count"]))
    streak = 0
    for flag in reversed(non_decreasing_flags):
        if not flag:
            break
        streak += 1
    window = int(convergence["stall_window_transitions"])
    outcome = str(convergence.get("outcome_on_stall") or "INVENTORY_NONCONVERGENT") if streak >= window else None
    return {
        "status": "PREREGISTERED",
        "distinct_head_transition_count": len(non_decreasing_flags),
        "consecutive_non_decreasing_unmapped_transitions": streak,
        "stall_window_transitions": window,
        "outcome": outcome,
        "history": history,
    }


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
    tracked_paths = _tracked_paths(repo, ref)
    for path in tracked_paths:
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

    tracked = set(tracked_paths)
    stale_exemptions = sorted(path for path in exemptions if path not in tracked)
    unmapped = sorted(c.path for c in candidates if not c.bundle_ids and c.exemption is None)
    multiply_mapped = sorted(c.path for c in candidates if len(c.bundle_ids) > 1)
    candidate_count = len(candidates)
    mapped_or_exempt_count = candidate_count - len(unmapped)
    complete = not unmapped and not stale_exemptions
    claimed = bool(registry.get("bundle_inventory_complete"))
    claim_matches = claimed == complete
    convergence_state = _convergence_state(
        repo=repo,
        ref=ref,
        policy=policy,
        candidate_count=candidate_count,
        unmapped_count=len(unmapped),
    )

    blocks: list[str] = []
    if unmapped:
        blocks.append("UNMAPPED_GOVERNANCE_SURFACES")
    if stale_exemptions:
        blocks.append("STALE_EXACT_EXEMPTIONS")
    if not claim_matches:
        blocks.append("REGISTRY_INVENTORY_COMPLETENESS_CLAIM_MISMATCH")

    scanner = policy.get("scanner_contract") or {}
    floor = scanner.get("candidate_total_floor")
    if isinstance(floor, int) and candidate_count < floor:
        blocks.append("INVENTORY_SCANNER_NARROWING_OR_SURFACE_LOSS")
    if convergence_state.get("outcome") == "INVENTORY_NONCONVERGENT":
        blocks.append("INVENTORY_NONCONVERGENT")

    return {
        "schema": "SPORTSEDGE_FREEZE_INVENTORY_AUDIT_V1",
        "ref": ref,
        "resolved_head_sha": _git(repo, "rev-parse", ref).strip(),
        "scanner_contract_sha256": _scanner_contract_sha256(policy),
        "candidate_count": candidate_count,
        "mapped_or_exactly_exempt_count": mapped_or_exempt_count,
        "unmapped_count": len(unmapped),
        "candidates": [c.as_dict() for c in candidates],
        "unmapped_paths": unmapped,
        "stale_exemptions": stale_exemptions,
        "multiply_mapped_paths": multiply_mapped,
        "convergence": convergence_state,
        "computed_complete": complete,
        "registry_claimed_complete": claimed,
        "claim_matches_computation": claim_matches,
        "release_blocks": blocks,
        "authority": dict(policy.get("authority") or {}),
    }


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
