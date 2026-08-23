"""Versioned NFL simulator validation profile built from real-history evidence.

Historical key-number frequencies are validation targets only. The profile must
never be consumed as simulator probability mass.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_REQUIRED_KEYS = (-7, -3, 3, 7)
KEY_NUMBER_CONTRACT = "EMERGENT_VALIDATION_TARGET_V1"


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def build_nfl_simulator_profile(audit: Mapping[str, Any], *, version: str) -> dict[str, Any]:
    if audit.get("provenance") != "REAL_PUBLIC_HISTORY":
        raise ValueError("REAL_HISTORY_REQUIRED")
    source_sha256 = audit.get("source_sha256")
    if not _valid_sha256(source_sha256):
        raise ValueError("SOURCE_SHA256_INVALID")
    seasons = [int(x) for x in audit.get("seasons", [])]
    if len(set(seasons)) < 2:
        raise ValueError("MULTI_SEASON_HISTORY_REQUIRED")
    raw = audit.get("signed_margin_pmf")
    if not isinstance(raw, Mapping):
        raise ValueError("SIGNED_MARGIN_PMF_REQUIRED")

    targets: dict[int, float] = {}
    for key in _REQUIRED_KEYS:
        value = raw.get(str(key), raw.get(key))
        if value is None:
            raise ValueError(f"SIGNED_KEY_FREQUENCY_MISSING:{key}")
        value = float(value)
        if value < 0:
            raise ValueError(f"SIGNED_KEY_FREQUENCY_NEGATIVE:{key}")
        targets[key] = value
    if sum(targets.values()) >= 1.0:
        raise ValueError("SIGNED_KEY_FREQUENCY_INVALID_SUM")

    if not version or not isinstance(version, str):
        raise ValueError("PROFILE_VERSION_REQUIRED")

    return {
        "version": version,
        "key_number_contract": KEY_NUMBER_CONTRACT,
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_sha256": str(source_sha256).lower(),
        "seasons": sorted(set(seasons)),
        "validation_target_key_frequency": targets,
    }


def validate_profile_fit(
    profile: Mapping[str, Any],
    simulated_signed_pmf: Mapping[int, float],
    *,
    max_abs_error: float,
) -> dict[str, Any]:
    if profile.get("key_number_contract") != KEY_NUMBER_CONTRACT:
        raise ValueError("EMERGENT_KEY_NUMBER_CONTRACT_REQUIRED")
    if max_abs_error < 0:
        raise ValueError("max_abs_error must be nonnegative")
    target = profile.get("validation_target_key_frequency")
    if not isinstance(target, Mapping):
        raise ValueError("PROFILE_KEY_FREQUENCY_TARGET_MISSING")

    per_key: dict[int, dict[str, float | bool]] = {}
    passed = True
    for key in _REQUIRED_KEYS:
        empirical = float(target[key])
        simulated = float(simulated_signed_pmf[key])
        error = abs(simulated - empirical)
        key_pass = error <= max_abs_error
        passed = passed and key_pass
        per_key[key] = {
            "historical_target": empirical,
            "simulated_emergent": simulated,
            "abs_error": error,
            "pass": key_pass,
        }
    return {
        "pass": passed,
        "contract": KEY_NUMBER_CONTRACT,
        "max_abs_error": float(max_abs_error),
        "per_key": per_key,
    }
