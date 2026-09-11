"""Secret-safe failover decisions for live MLB odds acquisition.

The native Odds API adapter intentionally records per-event failures instead of
raising them. That is useful for cardinality/audit, but it also means a key can
be exhausted or rejected for every event while the outer keyring sees a normal
return value. This module defines the one condition under which production may
rotate to the next configured key: zero quotes/results and provider-fetch
failures for every attempted event. Model/identity/feature failures never cause
credential rotation.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

_FETCH_PREFIX = "ODDS_API_FETCH_FAILED:"


def _reason(row: Mapping[str, Any]) -> str:
    return str(row.get("reason") or "")


def _is_provider_fetch_failure(row: Mapping[str, Any]) -> bool:
    """Recognize direct or exception-wrapped transport/fetch failures only."""
    if str(row.get("stage") or "") != "ODDS_API":
        return False
    reason = _reason(row)
    if reason.startswith(_FETCH_PREFIX):
        return True
    return _FETCH_PREFIX in reason


def should_rotate_odds_key(
    *,
    run_status: str,
    results: Iterable[Any],
    source_failures: Iterable[Mapping[str, Any]],
) -> bool:
    """Return True only for an all-provider fetch failure with no output."""
    if str(run_status) != "NO_QUOTES":
        return False
    if any(True for _ in results):
        return False
    failures = list(source_failures)
    if not failures:
        return False
    odds_fetches = [row for row in failures if _is_provider_fetch_failure(row)]
    if not odds_fetches:
        return False
    non_fetch = [row for row in failures if not _is_provider_fetch_failure(row)]
    blocking_non_fetch = [
        row
        for row in non_fetch
        if str(row.get("stage") or "") in {"ODDS_API", "ODDS_API_KEY_FAILOVER"}
    ]
    return not blocking_non_fetch
