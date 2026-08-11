"""Validate fixture-backed deployment attestations without self-promoting markets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class AttestationError(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AttestationError("attestation requirements must be an object")
    return data


def validate_attestation(
    attestation: Mapping[str, Any],
    *,
    requirements_path: str | Path = "config/attestation_requirements.json",
) -> dict[str, Any]:
    if not isinstance(attestation, Mapping):
        raise AttestationError("attestation must be an object")
    reqs = _load(requirements_path)
    market = str(attestation.get("market", ""))
    req = reqs.get("markets", {}).get(market)
    if not isinstance(req, Mapping):
        raise AttestationError(f"no attestation requirements for market {market!r}")
    expected_fixture = req.get("fixture_sha256")
    if not expected_fixture:
        raise AttestationError(f"fixture hash requirement unresolved for {market}")
    checks = {
        "verdict": attestation.get("verdict") == req.get("required_verdict"),
        "engine_version": attestation.get("engine_version") == req.get("engine_version"),
        "feature_version": attestation.get("feature_version") == req.get("feature_version"),
        "fixture_sha256": attestation.get("fixture_sha256") == expected_fixture,
        "ci_commit_sha": isinstance(attestation.get("ci_commit_sha"), str) and len(attestation.get("ci_commit_sha")) == 40,
        "test_name": isinstance(attestation.get("test_name"), str) and bool(attestation.get("test_name").strip()),
    }
    return {
        "market": market,
        "eligible_for_promotion": all(checks.values()),
        "checks": checks,
        "expected": dict(req),
    }
