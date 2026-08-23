"""Fail-closed football VALIDATED_MATH evidence attestation.

A caller does not get to promote math by setting ``math_valid=True``. This
module derives that state from a hash-bound simulator validation artifact whose
provenance, multi-season history, signed NFL key coverage, and emergent-frequency
fit are all mechanically checked.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_REQUIRED_SIGNED_KEYS = (-7, -3, 3, 7)
_REQUIRED_KEY_CONTRACT = "EMERGENT_VALIDATION_TARGET_V1"


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _canonical_sha256(artifact: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(artifact), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def attest_validated_math(artifact: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(artifact)
    if data.get("provenance") != "REAL_PUBLIC_HISTORY":
        raise ValueError("REAL_PUBLIC_HISTORY_REQUIRED")
    if not _valid_sha256(data.get("source_sha256")):
        raise ValueError("SOURCE_SHA256_INVALID")
    if not isinstance(data.get("profile_version"), str) or not data["profile_version"].strip():
        raise ValueError("PROFILE_VERSION_REQUIRED")
    if data.get("key_number_contract") != _REQUIRED_KEY_CONTRACT:
        raise ValueError("EMERGENT_KEY_NUMBER_CONTRACT_REQUIRED")

    seasons_raw = data.get("seasons")
    if not isinstance(seasons_raw, (list, tuple)):
        raise ValueError("MULTI_SEASON_HISTORY_REQUIRED")
    seasons = sorted({int(value) for value in seasons_raw})
    if len(seasons) < 2:
        raise ValueError("MULTI_SEASON_HISTORY_REQUIRED")

    keys_raw = data.get("key_numbers")
    if not isinstance(keys_raw, (list, tuple)):
        raise ValueError("SIGNED_KEY_COVERAGE_INCOMPLETE")
    keys = {int(value) for value in keys_raw}
    if not set(_REQUIRED_SIGNED_KEYS).issubset(keys):
        raise ValueError("SIGNED_KEY_COVERAGE_INCOMPLETE")

    tolerance = float(data.get("max_allowed_abs_error", -1.0))
    if tolerance < 0.0:
        raise ValueError("KEY_ERROR_TOLERANCE_INVALID")

    errors_raw = data.get("per_key_abs_error")
    if not isinstance(errors_raw, Mapping):
        raise ValueError("PER_KEY_ERROR_REQUIRED")

    errors: dict[int, float] = {}
    for key in _REQUIRED_SIGNED_KEYS:
        if str(key) in errors_raw:
            value = errors_raw[str(key)]
        elif key in errors_raw:
            value = errors_raw[key]
        else:
            raise ValueError("PER_KEY_ERROR_REQUIRED")
        error = float(value)
        if error < 0.0:
            raise ValueError("PER_KEY_ERROR_INVALID")
        errors[key] = error

    failed = sorted(key for key, error in errors.items() if error > tolerance)
    artifact_sha256 = _canonical_sha256(data)
    return {
        "math_valid": not failed,
        "attestation": "VALIDATED_MATH" if not failed else "BLOCKED_MATH",
        "artifact_sha256": artifact_sha256,
        "source_sha256": str(data["source_sha256"]).lower(),
        "profile_version": data["profile_version"],
        "key_number_contract": _REQUIRED_KEY_CONTRACT,
        "seasons": seasons,
        "signed_key_numbers": list(_REQUIRED_SIGNED_KEYS),
        "max_allowed_abs_error": tolerance,
        "per_key_abs_error": {str(key): errors[key] for key in _REQUIRED_SIGNED_KEYS},
        "failed_keys": failed,
    }
