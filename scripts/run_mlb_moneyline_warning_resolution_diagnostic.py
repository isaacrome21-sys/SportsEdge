#!/usr/bin/env python3
"""Zero-authority MLB MONEYLINE warning-resolution diagnostic.

Evaluates the five frozen V2 warning classes against evidence supplied for the
exact frozen lane identity. It emits findings only; it never creates a warning
clearance receipt and never changes deployment, staking, promotion, or OFFICIAL
state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "mlb_moneyline_warning_resolution_diagnostic_v1"
WARNINGS = (
    "CALIBRATION_BAND_MISS",
    "KEY_NUMBER_TOLERANCE_MISS",
    "NONCRITICAL_PROVENANCE_HASH_MISSING",
    "THREE_MODE_PARITY_MISS",
    "NONCRITICAL_DIAGNOSTIC_MISSING",
)
ZERO_AUTHORITY = {
    "promotion_authority": False,
    "deployment_change_allowed": False,
    "staking_change_allowed": False,
    "official_change_allowed": False,
}


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_sha(value: object) -> bool:
    s = str(value or "")
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def identity_from(readiness: Mapping[str, Any]) -> dict[str, str]:
    identity = {
        "lane_id": str(readiness.get("lane_id") or ""),
        "model_artifact_sha256": str(readiness.get("model_artifact_sha256") or ""),
        "market_definition_sha256": str(readiness.get("market_definition_sha256") or ""),
        "policy_id": str(readiness.get("policy_id") or ""),
        "policy_sha256": str(readiness.get("policy_sha256") or ""),
    }
    if not identity["lane_id"] or not identity["policy_id"]:
        raise ValueError("frozen lane identity incomplete")
    for key in ("model_artifact_sha256", "market_definition_sha256", "policy_sha256"):
        if not valid_sha(identity[key]):
            raise ValueError(f"invalid frozen identity digest: {key}")
    return identity


def evidence_ref(path: Path) -> dict[str, str]:
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def bound_to_identity(doc: Mapping[str, Any], identity: Mapping[str, str]) -> bool:
    return all(str(doc.get(k) or "") == v for k, v in identity.items())


def find_docs(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    docs: list[tuple[Path, dict[str, Any]]] = []
    if not root.exists():
        return docs
    for path in sorted(root.rglob("*.json")):
        try:
            docs.append((path, load_object(path)))
        except Exception:
            continue
    return docs


def docs_matching(docs, identity, predicates):
    out = []
    for path, doc in docs:
        if not bound_to_identity(doc, identity):
            continue
        if any(pred(doc) for pred in predicates):
            out.append((path, doc))
    return out


def finding(warning: str, matches, reason: str) -> dict[str, Any]:
    # This diagnostic may prove CLEARED. SIGNED_OFF is deliberately never
    # self-issued: human actor/reason approval belongs to the later clearance
    # receipt workflow.
    cleared = any(
        str(doc.get("warning_status") or doc.get("status") or "").upper() in
        {"CLEARED", "PASS", "PASSED"} and
        str(doc.get("warning") or doc.get("warning_id") or warning) == warning
        for _, doc in matches
    )
    return {
        "warning": warning,
        "status": "CLEARED" if cleared else "UNRESOLVED",
        "reason": "bound evidence explicitly reports pass/cleared" if cleared else reason,
        "evidence_references": [evidence_ref(path) for path, _ in matches],
        "human_signoff_required": not cleared,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--readiness", type=Path, default=Path("artifacts/mlb_moneyline_authority_readiness_report.json"))
    p.add_argument("--evidence-root", type=Path, default=Path("data"))
    p.add_argument("--policy", type=Path, default=Path("config/promotion_evidence_policy_v2.json"))
    p.add_argument("--output", type=Path, default=Path("artifacts/mlb_moneyline_warning_resolution_diagnostic.json"))
    args = p.parse_args()

    readiness = load_object(args.readiness)
    identity = identity_from(readiness)
    if sha256_file(args.policy) != identity["policy_sha256"]:
        raise SystemExit("policy SHA does not match frozen lane identity")

    policy = load_object(args.policy)
    frozen = tuple(policy.get("warning_only_on_probation") or ())
    if frozen != WARNINGS:
        raise SystemExit(f"frozen warning universe mismatch: {frozen!r}")

    docs = find_docs(args.evidence_root)
    rules = {
        "CALIBRATION_BAND_MISS": (
            lambda d: "calibration" in str(d.get("schema_version", "")).lower()
            or "calibration" in str(d.get("diagnostic_type", "")).lower(),
        ),
        "KEY_NUMBER_TOLERANCE_MISS": (
            lambda d: "key_number" in json.dumps(d, sort_keys=True).lower(),
        ),
        "NONCRITICAL_PROVENANCE_HASH_MISSING": (
            lambda d: "provenance" in str(d.get("schema_version", "")).lower()
            or "provenance" in json.dumps(d, sort_keys=True).lower(),
        ),
        "THREE_MODE_PARITY_MISS": (
            lambda d: "parity" in str(d.get("schema_version", "")).lower()
            or "three_mode" in json.dumps(d, sort_keys=True).lower(),
        ),
        "NONCRITICAL_DIAGNOSTIC_MISSING": (
            lambda d: "diagnostic" in str(d.get("schema_version", "")).lower()
            or bool(d.get("diagnostics")),
        ),
    }

    findings = {}
    for warning in WARNINGS:
        matches = docs_matching(docs, identity, rules[warning])
        findings[warning] = finding(
            warning,
            matches,
            "no explicit pass/cleared finding bound to the exact frozen lane identity",
        )

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = {
        "schema_version": SCHEMA,
        "generated_at_utc": now,
        "identity": identity,
        "policy_evidence": evidence_ref(args.policy),
        "readiness_evidence": evidence_ref(args.readiness),
        "evidence_root": args.evidence_root.as_posix(),
        "findings": findings,
        "all_warnings_resolved": all(x["status"] == "CLEARED" for x in findings.values()),
        "note": (
            "SIGNED_OFF is intentionally not emitted by this diagnostic. Human signoff, "
            "where governance permits it, belongs to the separate clearance-receipt step."
        ),
        **ZERO_AUTHORITY,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["all_warnings_resolved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
