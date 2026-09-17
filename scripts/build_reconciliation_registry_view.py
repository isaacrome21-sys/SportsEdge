#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "SPORTSEDGE_RECONCILIATION_COVERAGE_EXTENSION_V1"


def load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_sha256(value: object, error: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise SystemExit(error)
    return text


def validate_extension(extension: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    if extension.get("schema") != SCHEMA:
        raise SystemExit("COVERAGE_EXTENSION_SCHEMA_INVALID")
    if any(bool(v) for v in (extension.get("authority") or {}).values()):
        raise SystemExit("COVERAGE_EXTENSION_AUTHORITY_ESCALATION")
    known = {str(b.get("bundle_id")) for b in (registry.get("bundles") or ())}
    bundle_extensions = extension.get("bundle_extensions") or {}
    if not isinstance(bundle_extensions, Mapping):
        raise SystemExit("COVERAGE_EXTENSION_BUNDLES_INVALID")
    for bundle_id, selectors in bundle_extensions.items():
        if str(bundle_id) not in known:
            raise SystemExit(f"COVERAGE_EXTENSION_UNKNOWN_BUNDLE:{bundle_id}")
        if not isinstance(selectors, Mapping):
            raise SystemExit(f"COVERAGE_EXTENSION_SELECTOR_INVALID:{bundle_id}")
        for key in ("coverage_paths", "coverage_prefixes"):
            values = selectors.get(key) or []
            if not isinstance(values, list):
                raise SystemExit(f"COVERAGE_EXTENSION_LIST_REQUIRED:{bundle_id}:{key}")
            for value in values:
                if not isinstance(value, str) or not value:
                    raise SystemExit(f"COVERAGE_EXTENSION_PATH_INVALID:{bundle_id}:{key}")
                if any(token in value for token in ("*", "?", "[", "]")):
                    raise SystemExit(f"COVERAGE_EXTENSION_WILDCARD_FORBIDDEN:{value}")
    exemptions = extension.get("exact_exemptions") or {}
    if not isinstance(exemptions, Mapping):
        raise SystemExit("COVERAGE_EXTENSION_EXEMPTIONS_INVALID")
    for path, reason in exemptions.items():
        if not isinstance(path, str) or not path or not isinstance(reason, str) or not reason:
            raise SystemExit("COVERAGE_EXTENSION_EXEMPTION_INVALID")
        if any(token in path for token in ("*", "?", "[", "]")):
            raise SystemExit(f"COVERAGE_EXTENSION_EXEMPTION_WILDCARD_FORBIDDEN:{path}")

    claim = extension.get("inventory_completion_claim")
    if claim is not None:
        if not isinstance(claim, Mapping):
            raise SystemExit("INVENTORY_COMPLETION_CLAIM_INVALID")
        if claim.get("status") != "HOSTED_AUDIT_ZERO_UNMAPPED":
            raise SystemExit("INVENTORY_COMPLETION_CLAIM_STATUS_INVALID")
        if claim.get("set_effective_registry_complete") is not True:
            raise SystemExit("INVENTORY_COMPLETION_CLAIM_NOT_EFFECTIVE")
        if int(claim.get("candidate_count", -1)) < 1 or int(claim.get("unmapped_count", -1)) != 0:
            raise SystemExit("INVENTORY_COMPLETION_CLAIM_COUNTS_INVALID")
        head = str(claim.get("proof_head_sha") or "")
        if len(head) != 40:
            raise SystemExit("INVENTORY_COMPLETION_CLAIM_HEAD_INVALID")
        if int(claim.get("proof_run_id", 0)) <= 0 or int(claim.get("proof_artifact_id", 0)) <= 0:
            raise SystemExit("INVENTORY_COMPLETION_CLAIM_PROVENANCE_INVALID")
        _validate_sha256(claim.get("proof_artifact_digest_sha256"), "INVENTORY_COMPLETION_CLAIM_ARTIFACT_DIGEST_INVALID")
        _validate_sha256(claim.get("proof_extension_canonical_sha256"), "INVENTORY_COMPLETION_CLAIM_EXTENSION_DIGEST_INVALID")

    dispositions = extension.get("bundle_dispositions") or {}
    if not isinstance(dispositions, Mapping):
        raise SystemExit("BUNDLE_DISPOSITIONS_INVALID")
    for bundle_id, disposition in dispositions.items():
        if str(bundle_id) not in known:
            raise SystemExit(f"BUNDLE_DISPOSITION_UNKNOWN_BUNDLE:{bundle_id}")
        if not isinstance(disposition, Mapping):
            raise SystemExit(f"BUNDLE_DISPOSITION_INVALID:{bundle_id}")
        if disposition.get("state") != "REVOKED":
            raise SystemExit(f"BUNDLE_DISPOSITION_ONLY_REVOCATION_ALLOWED_PRE_MERGE:{bundle_id}")
        if not str(disposition.get("revoked_at") or ""):
            raise SystemExit(f"BUNDLE_REVOCATION_TIMESTAMP_REQUIRED:{bundle_id}")
        if disposition.get("prior_forward_clock_invalidated") is not True:
            raise SystemExit(f"BUNDLE_REVOCATION_CLOCK_INVALIDATION_REQUIRED:{bundle_id}")
        if not str(disposition.get("reason") or ""):
            raise SystemExit(f"BUNDLE_REVOCATION_REASON_REQUIRED:{bundle_id}")


def _registered_refreeze_supersedes_revocation(existing: object, extension_disposition: Mapping[str, Any]) -> bool:
    """Allow a newer registry refreeze to supersede an older extension revocation.

    The extension is deliberately limited to fail-closed REVOKED states. A later,
    explicitly registered REFROZEN state lives in the governed base registry. It
    may supersede that stale revocation only when the refreeze carries the minimum
    identity and forward-clock fields. Other disposition disagreements remain a
    hard conflict.
    """
    if not isinstance(existing, Mapping):
        return False
    if extension_disposition.get("state") != "REVOKED" or existing.get("state") != "REFROZEN":
        return False
    return all(str(existing.get(key) or "") for key in ("new_bundle_id", "new_freeze_sha", "forward_clock_restart_at"))


def _parse_revoked_at(value: object) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit("BUNDLE_REVOCATION_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit("BUNDLE_REVOCATION_TIMESTAMP_NAIVE")
    return parsed


def _merge_fail_closed_revocations(
    existing: object, extension_disposition: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Resolve two REVOKED records by preserving the earlier invalidation.

    A later registry revocation must never weaken an already-effective extension
    revocation by moving the invalidation clock forward. Conversely, an earlier
    registry revocation is stricter and is retained. This helper can only return
    a REVOKED disposition with prior-forward-clock invalidation true; it cannot
    create authority or an active/refrozen state.
    """
    if not isinstance(existing, Mapping):
        return None
    if existing.get("state") != "REVOKED" or extension_disposition.get("state") != "REVOKED":
        return None
    if existing.get("prior_forward_clock_invalidated") is not True:
        return None
    if extension_disposition.get("prior_forward_clock_invalidated") is not True:
        return None
    existing_at = _parse_revoked_at(existing.get("revoked_at"))
    extension_at = _parse_revoked_at(extension_disposition.get("revoked_at"))
    chosen = existing if existing_at <= extension_at else extension_disposition
    return copy.deepcopy(dict(chosen))


def merge_view(
    policy: Mapping[str, Any], registry: Mapping[str, Any], extension: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validate_extension(extension, registry)
    effective_policy = copy.deepcopy(dict(policy))
    effective_registry = copy.deepcopy(dict(registry))

    extension_exemptions = {str(k): str(v) for k, v in (extension.get("exact_exemptions") or {}).items()}
    exact = effective_policy.setdefault("exact_exemptions", {})
    if not isinstance(exact, dict):
        raise SystemExit("EFFECTIVE_POLICY_EXEMPTIONS_NOT_OBJECT")
    for path, reason in sorted(extension_exemptions.items()):
        if path in exact and str(exact[path]) != reason:
            raise SystemExit(f"COVERAGE_EXTENSION_EXEMPTION_CONFLICT:{path}")
        exact[path] = reason

    by_id = {str(bundle["bundle_id"]): bundle for bundle in effective_registry.get("bundles") or []}
    added_paths = 0
    added_prefixes = 0
    for bundle_id, selectors in sorted((extension.get("bundle_extensions") or {}).items()):
        bundle = by_id[str(bundle_id)]
        for key in ("coverage_paths", "coverage_prefixes"):
            existing = [str(v) for v in (bundle.get(key) or [])]
            additions = [str(v) for v in (selectors.get(key) or [])]
            merged = sorted(set(existing).union(additions))
            bundle[key] = merged
            if key == "coverage_paths":
                added_paths += len(set(additions) - set(existing))
            else:
                added_prefixes += len(set(additions) - set(existing))

    dispositions = extension.get("bundle_dispositions") or {}
    superseded_revocations: list[str] = []
    merged_revocations: list[str] = []
    for bundle_id, disposition in sorted(dispositions.items()):
        bundle = by_id[str(bundle_id)]
        existing = bundle.get("disposition")
        if existing is not None and existing != disposition:
            if _registered_refreeze_supersedes_revocation(existing, disposition):
                superseded_revocations.append(str(bundle_id))
                continue
            merged_revocation = _merge_fail_closed_revocations(existing, disposition)
            if merged_revocation is not None:
                bundle["disposition"] = merged_revocation
                merged_revocations.append(str(bundle_id))
                continue
            raise SystemExit(f"BUNDLE_DISPOSITION_CONFLICT:{bundle_id}")
        bundle["disposition"] = copy.deepcopy(dict(disposition))

    claim = extension.get("inventory_completion_claim") or {}
    if claim:
        effective_registry["bundle_inventory_complete"] = True
        effective_registry["inventory_block_reason"] = None

    extension_sha = canonical_sha256(extension)
    attestation = {
        "schema": "SPORTSEDGE_RECONCILIATION_COVERAGE_ATTESTATION_V1",
        "extension_canonical_sha256": extension_sha,
        "bundle_extension_count": len(extension.get("bundle_extensions") or {}),
        "exact_exemption_count": len(extension_exemptions),
        "added_coverage_path_count": added_paths,
        "added_coverage_prefix_count": added_prefixes,
        "bundle_disposition_count": len(dispositions),
        "superseded_extension_revocations": sorted(superseded_revocations),
        "merged_fail_closed_revocations": sorted(merged_revocations),
        "inventory_completion_claim_applied": bool(claim),
        "inventory_completion_proof": dict(claim) if claim else None,
        "scanner_discovery_contract_changed": False,
        "coverage_only_broadening": True,
        "authority": {key: False for key in ("model", "truth_gate", "promotion", "staking", "official", "validation_attempt", "readout")},
    }
    return effective_policy, effective_registry, attestation


def write_json(path: str | Path, value: object) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic effective reconciliation policy/registry view from exact coverage extensions.")
    parser.add_argument("--policy", default="config/freeze_inventory_policy_v1.json")
    parser.add_argument("--registry", default="config/freeze_reconciliation_registry_v1.json")
    parser.add_argument("--extension", default="config/reconciliation_coverage_v1.json")
    parser.add_argument("--output-policy", required=True)
    parser.add_argument("--output-registry", required=True)
    parser.add_argument("--attestation", required=True)
    args = parser.parse_args()

    effective_policy, effective_registry, attestation = merge_view(
        load(args.policy), load(args.registry), load(args.extension)
    )
    write_json(args.output_policy, effective_policy)
    write_json(args.output_registry, effective_registry)
    write_json(args.attestation, attestation)
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
