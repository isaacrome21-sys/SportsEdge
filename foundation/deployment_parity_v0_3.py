#!/usr/bin/env python3
"""SportsEdge deployment-parity guard v0.3.

Consumes the external validation registry and a runtime capability attestation.
Statistical validation is never sufficient by itself: official eligibility is
intersected with exact registry-version parity, artifact identity + runtime-load
attestation, explicit deployment requirements, and market scope restrictions.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

CAPABILITY_REQUIREMENTS = {
    "team total": "team_total_line_policy_v1",
    "pitcher walks": "rolling_pitcher_walks_recalibration_45d",
    "hits": "shared_game_effect_sigma_0_20",
    "total bases": "shared_game_effect_sigma_0_20",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _registry_check(registry: Dict[str, Any], capabilities: Dict[str, Any]) -> Dict[str, Any]:
    if registry.get("policy") != "fail_closed_external_registry_with_deployment_parity":
        return {"status": "FAIL_CLOSED", "reason": "UNSUPPORTED_REGISTRY_POLICY"}
    schema = str(registry.get("schema_version") or "")
    runtime_schema = str(capabilities.get("registry_schema_version") or "")
    if not schema or runtime_schema != schema:
        return {
            "status": "FAIL_CLOSED",
            "reason": "REGISTRY_RUNTIME_VERSION_MISMATCH",
            "registry_schema_version": schema,
            "runtime_registry_schema_version": runtime_schema or None,
        }
    return {"status": "PASS", "schema_version": schema}


def _artifact_check(market: str, rec: Dict[str, Any], runtime_root: Path, capabilities: Dict[str, Any]) -> Dict[str, Any]:
    art = rec.get("artifact")
    if not art:
        return {"status": "NOT_REQUIRED"}
    rel = art.get("path")
    expected = art.get("artifact_hash")
    if not rel or not expected:
        return {"status": "FAIL_CLOSED", "reason": "INCOMPLETE_ARTIFACT_DECLARATION"}
    path = runtime_root / rel
    if not path.is_file():
        return {
            "status": "FAIL_CLOSED",
            "reason": "MISSING_REQUIRED_ARTIFACT",
            "market": market,
            "path": rel,
            "expected_hash": expected,
        }
    actual = sha256_file(path)
    if actual != expected:
        return {
            "status": "FAIL_CLOSED",
            "reason": "ARTIFACT_HASH_MISMATCH",
            "market": market,
            "path": rel,
            "expected_hash": expected,
            "actual_hash": actual,
        }
    loaded = capabilities.get("loaded_artifacts") or {}
    if loaded.get(market) != expected:
        return {
            "status": "FAIL_CLOSED",
            "reason": "ARTIFACT_PRESENT_BUT_RUNTIME_LOAD_UNPROVEN",
            "market": market,
            "path": rel,
            "expected_hash": expected,
            "runtime_loaded_hash": loaded.get(market),
        }
    return {"status": "PASS", "path": rel, "hash": actual, "runtime_loaded_hash": expected}


def _scope_check(market: str, rec: Dict[str, Any], candidate_line: Optional[float]) -> Dict[str, Any]:
    scope = rec.get("scope") or {}
    if market == "team total" and candidate_line is not None:
        blocked = {str(x) for x in scope.get("blocked_lines", [])}
        caution = {str(x) for x in scope.get("caution_lines", [])}
        allowed = {str(x) for x in scope.get("allowed_lines", [])}
        line = str(float(candidate_line))
        if line in blocked:
            return {"status": "BLOCKED", "reason": "REGISTRY_SCOPE_BLOCKED_LINE", "line": line}
        if line in caution:
            return {"status": "CAUTION", "reason": "REGISTRY_SCOPE_CAUTION_LINE", "line": line}
        if allowed:
            if "5.5+" in allowed and float(candidate_line) >= 5.5:
                return {"status": "PASS", "line": line}
            return {"status": "BLOCKED", "reason": "REGISTRY_SCOPE_NOT_ALLOWED", "line": line}
    return {"status": "PASS"}


def market_deployment_status(
    registry: Dict[str, Any],
    market: str,
    runtime_root: Path,
    capabilities: Optional[Dict[str, Any]] = None,
    candidate_line: Optional[float] = None,
) -> Dict[str, Any]:
    capabilities = capabilities or {}
    registry_check = _registry_check(registry, capabilities)
    if registry_check["status"] != "PASS":
        return {**registry_check, "market": market, "status": "BLOCKED_DEPLOYMENT_PARITY"}

    rec = (registry.get("markets") or {}).get(market)
    if rec is None:
        return {"market": market, "status": "BLOCKED", "reason": "MARKET_ABSENT_FROM_REGISTRY"}
    if not rec.get("official_eligible", False):
        return {
            "market": market,
            "status": "BLOCKED",
            "reason": "REGISTRY_NOT_OFFICIAL_ELIGIBLE",
            "registry_status": rec.get("status"),
        }

    artifact = _artifact_check(market, rec, runtime_root, capabilities)
    if artifact["status"] == "FAIL_CLOSED":
        return {
            "market": market,
            "status": "BLOCKED_DEPLOYMENT_PARITY",
            "reason": artifact["reason"],
            "artifact": artifact,
            "registry_status": rec.get("status"),
        }

    cap = CAPABILITY_REQUIREMENTS.get(market)
    if cap and capabilities.get(cap) is not True:
        return {
            "market": market,
            "status": "BLOCKED_DEPLOYMENT_PARITY",
            "reason": "MISSING_RUNTIME_CAPABILITY_ATTESTATION",
            "required_capability": cap,
            "deployment_requirement": rec.get("deployment_requirement"),
            "registry_status": rec.get("status"),
        }

    # Any registry deployment requirement not otherwise captured must be
    # explicitly attested. This prevents future v1.7+ requirements from being
    # silently ignored by an older runtime.
    requirement = rec.get("deployment_requirement")
    if requirement:
        verified_requirements = set(capabilities.get("verified_requirements") or [])
        if cap is None and requirement not in verified_requirements:
            return {
                "market": market,
                "status": "BLOCKED_DEPLOYMENT_PARITY",
                "reason": "DEPLOYMENT_REQUIREMENT_UNATTESTED",
                "deployment_requirement": requirement,
                "registry_status": rec.get("status"),
            }

    scope = _scope_check(market, rec, candidate_line)
    if scope["status"] == "BLOCKED":
        return {
            "market": market,
            "status": "BLOCKED",
            "reason": scope["reason"],
            "scope": scope,
            "registry_status": rec.get("status"),
        }

    effective = "PASS_CAUTION" if rec.get("status") == "PASS_CAUTION" or scope["status"] == "CAUTION" else "PASS"
    return {
        "market": market,
        "status": effective,
        "reason": "REGISTRY_ELIGIBLE_AND_DEPLOYMENT_PARITY_VERIFIED",
        "registry_status": rec.get("status"),
        "registry_parity": registry_check,
        "artifact": artifact,
        "scope": scope,
    }


def audit_deployment_parity(
    registry: Dict[str, Any],
    runtime_root: Path,
    capabilities: Optional[Dict[str, Any]] = None,
    markets: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    capabilities = capabilities or {}
    names = list(markets) if markets is not None else list((registry.get("markets") or {}).keys())
    results = [market_deployment_status(registry, m, runtime_root, capabilities) for m in names]
    blocked = [r for r in results if r["status"].startswith("BLOCKED")]
    return {
        "policy": "REGISTRY_AUTHORIZATION_INTERSECT_DEPLOYMENT_PARITY",
        "registry_schema_version": registry.get("schema_version"),
        "runtime_registry_schema_version": capabilities.get("registry_schema_version"),
        "overall_status": "PASS" if not blocked else "FAIL_CLOSED",
        "blocked_count": len(blocked),
        "results": results,
    }
