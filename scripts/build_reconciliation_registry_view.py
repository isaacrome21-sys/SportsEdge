#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
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

    extension_sha = canonical_sha256(extension)
    attestation = {
        "schema": "SPORTSEDGE_RECONCILIATION_COVERAGE_ATTESTATION_V1",
        "extension_canonical_sha256": extension_sha,
        "bundle_extension_count": len(extension.get("bundle_extensions") or {}),
        "exact_exemption_count": len(extension_exemptions),
        "added_coverage_path_count": added_paths,
        "added_coverage_prefix_count": added_prefixes,
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
