"""Validate fixture-backed deployment attestations without self-promoting markets."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


class AttestationError(ValueError):
    pass


_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def _load(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AttestationError("attestation requirements must be an object")
    return data


def validate_attestation(
    attestation: Mapping[str, Any],
    *,
    requirements_path: str | Path = "config/attestation_requirements.json",
    expected_ci_commit_sha: str | None = None,
) -> dict[str, Any]:
    """Validate an attestation against frozen requirements and the tested CI commit.

    A syntactically valid SHA is not sufficient evidence. Promotion is fail-closed
    unless the caller supplies the exact CI commit expected for this attestation,
    and the attested SHA matches it exactly.
    """
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

    attested_sha = attestation.get("ci_commit_sha")
    expected_sha_valid = (
        isinstance(expected_ci_commit_sha, str)
        and bool(_SHA40_RE.fullmatch(expected_ci_commit_sha.lower()))
    )
    attested_sha_valid = (
        isinstance(attested_sha, str)
        and bool(_SHA40_RE.fullmatch(attested_sha.lower()))
    )

    checks = {
        "verdict": attestation.get("verdict") == req.get("required_verdict"),
        "engine_version": attestation.get("engine_version") == req.get("engine_version"),
        "feature_version": attestation.get("feature_version") == req.get("feature_version"),
        "fixture_sha256": attestation.get("fixture_sha256") == expected_fixture,
        "ci_commit_sha": (
            expected_sha_valid
            and attested_sha_valid
            and attested_sha.lower() == expected_ci_commit_sha.lower()
        ),
        "test_name": attestation.get("test_name") == req.get("required_test_name"),
    }
    return {
        "market": market,
        "eligible_for_promotion": all(checks.values()),
        "checks": checks,
        "expected": {**dict(req), "ci_commit_sha": expected_ci_commit_sha},
    }
