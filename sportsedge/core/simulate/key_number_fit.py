"""Extract signed NFL key-number frequencies as behavioral validation targets.

Historical ±3/±7 frequencies must never be fed back into the simulator as exact
probability mass. They are held-out targets used to judge emergent margins.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def extract_signed_key_frequency_targets_from_audit(
    audit: Mapping[str, Any],
    *,
    keys: Iterable[int] = (3, 7),
) -> dict[int, float]:
    """Return held-out signed frequency targets for ±key margins."""
    if audit.get("provenance") != "REAL_PUBLIC_HISTORY":
        raise ValueError("REAL_HISTORY_PROVENANCE_REQUIRED")
    if not str(audit.get("source_url", "")).startswith("https://"):
        raise ValueError("REAL_HISTORY_SOURCE_URL_REQUIRED")
    if not _valid_sha256(audit.get("source_sha256")):
        raise ValueError("SOURCE_SHA256_INVALID")
    seasons = audit.get("seasons")
    if not isinstance(seasons, list) or len(set(int(x) for x in seasons)) < 2:
        raise ValueError("REAL_HISTORY_REQUIRES_MULTIPLE_SEASONS")

    signed = audit.get("signed_margin_pmf")
    if not isinstance(signed, Mapping):
        raise ValueError("SIGNED_MARGIN_PMF_REQUIRED")

    out: dict[int, float] = {}
    for key in keys:
        k = abs(int(key))
        if k == 0:
            raise ValueError("KEY_NUMBER_MUST_BE_NONZERO")
        for margin in (-k, k):
            raw = signed.get(str(margin), signed.get(margin))
            if raw is None:
                raise ValueError(f"SIGNED_KEY_FREQUENCY_MISSING:{margin}")
            value = float(raw)
            if value < 0.0 or value >= 1.0:
                raise ValueError(f"SIGNED_KEY_FREQUENCY_INVALID:{margin}")
            out[margin] = value
    if sum(out.values()) >= 1.0:
        raise ValueError("SIGNED_KEY_FREQUENCY_SUM_INVALID")
    return dict(sorted(out.items()))


def fit_signed_key_mass_from_audit(
    audit: Mapping[str, Any],
    *,
    keys: Iterable[int] = (3, 7),
) -> dict[int, float]:
    """Compatibility alias returning validation targets, never simulator inputs.

    Kept temporarily so callers do not fail at import time. Passing this result as
    ``empirical_key_mass`` to KeyNumberMarginModel now fails closed.
    """
    return extract_signed_key_frequency_targets_from_audit(audit, keys=keys)
