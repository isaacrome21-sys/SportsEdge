"""Ordered, secret-safe failover for The Odds API credentials.

Keys are never logged or returned. A fetch attempt either returns a complete
provider snapshot or raises; failures are recorded only by 1-based key slot and
exception class/message. Provider/account quota exhaustion is terminal by default:
blindly rotating through more credentials can multiply paid/account probes after
an account has already told us it cannot serve another request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

T = TypeVar("T")


class OddsKeyringError(RuntimeError):
    pass


@dataclass(frozen=True)
class OddsKeyFailure:
    key_slot: int
    reason: str


@dataclass(frozen=True)
class OddsKeyringResult(Generic[T]):
    value: T
    key_slot: int
    failures: tuple[OddsKeyFailure, ...]


def _clean_keys(keys: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in keys:
        if not isinstance(raw, str):
            raise OddsKeyringError("ODDS_API_KEY_MALFORMED")
        key = raw.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    if not out:
        raise OddsKeyringError("ODDS_API_KEY_MISSING")
    return tuple(out)


def _quota_exhausted(exc: BaseException) -> bool:
    """Recognize provider exhaustion without depending on a specific HTTP class."""
    text = f"{type(exc).__name__}:{exc}".upper().replace(" ", "")
    return "OUT_OF_USAGE_CREDITS" in text or "BLOCKED_NO_CREDITS" in text


def fetch_with_key_failover(
    keys: Iterable[str],
    fetcher: Callable[[str], T],
    *,
    allow_quota_failover: bool = False,
) -> OddsKeyringResult[T]:
    """Fetch with ordered failover while failing closed on provider exhaustion.

    ``allow_quota_failover`` exists only for deployments where the operator has
    explicitly established that each key is backed by an independent quota/account.
    SportsEdge defaults to ``False`` so a 401 OUT_OF_USAGE_CREDITS cannot silently
    fan out across every configured credential.
    """
    clean = _clean_keys(keys)
    failures: list[OddsKeyFailure] = []
    for slot, key in enumerate(clean, start=1):
        try:
            return OddsKeyringResult(fetcher(key), slot, tuple(failures))
        except Exception as exc:
            # Never include the credential itself in diagnostics.
            failure = OddsKeyFailure(slot, f"{type(exc).__name__}: {exc}")
            failures.append(failure)
            if _quota_exhausted(exc) and not allow_quota_failover:
                raise OddsKeyringError(
                    f"ODDS_API_QUOTA_EXHAUSTED_TERMINAL:slot={slot}:{failure.reason}"
                ) from exc
    summary = "; ".join(f"slot={x.key_slot}:{x.reason}" for x in failures)
    raise OddsKeyringError(f"ODDS_API_ALL_KEYS_FAILED: {summary}")
