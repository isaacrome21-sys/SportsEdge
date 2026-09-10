"""Secret-safe failover decisions for live MLB odds acquisition.

The native Odds API adapter intentionally records per-event failures instead of
raising them. That is useful for cardinality/audit, but it also means a key can
be exhausted or rejected for every event while the outer keyring sees a normal
return value. This module defines the narrow condition under which production
may treat native acquisition as rotatable/unusable: zero quotes/results and
provider-fetch failures for every attempted event, excluding terminal provider
states such as account quota exhaustion. Model/identity/feature failures never
cause credential rotation.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .odds_keyring import is_terminal_odds_failure

_FETCH_PREFIX = "ODDS_API_FETCH_FAILED:"


def _reason(row: Mapping[str, Any]) -> str:
    return str(row.get("reason") or "")


def should_rotate_odds_key(*, run_status: str, results: Iterable[Any], source_failures: Iterable[Mapping[str, Any]]) -> bool:
    """Return True only for a non-terminal all-event provider fetch failure.

    This keeps failover narrow and deterministic. It must not rotate around
    account exhaustion, model, lineup, chronology, identity, feature, or Truth
    Gate failures.
    """
    if str(run_status) != "NO_QUOTES":
        return False
    if any(True for _ in results):
        return False
    failures = list(source_failures)
    if not failures:
        return False
    odds_fetches = [
        row for row in failures
        if str(row.get("stage") or "") == "ODDS_API" and _reason(row).startswith(_FETCH_PREFIX)
    ]
    if not odds_fetches:
        return False
    if any(is_terminal_odds_failure(_reason(row)) for row in odds_fetches):
        return False
    non_fetch = [
        row for row in failures
        if not (str(row.get("stage") or "") == "ODDS_API" and _reason(row).startswith(_FETCH_PREFIX))
    ]
    # Roster/feature diagnostics may coexist with a transient provider failure,
    # but any other odds-provider failure means the request itself reached the
    # provider and should be surfaced rather than hidden by rotating credentials.
    blocking_non_fetch = [
        row for row in non_fetch
        if str(row.get("stage") or "") in {"ODDS_API", "ODDS_API_KEY_FAILOVER"}
    ]
    return not blocking_non_fetch
