"""Ordered, secret-safe failover for The Odds API credentials.

Keys are never logged or returned. A fetch attempt either returns a complete
provider snapshot or raises; failures are recorded only by 1-based key slot and
exception class/message. The caller controls the actual provider fetch.

``OUT_OF_USAGE_CREDITS`` is account-terminal. SportsEdge keys may be multiple
slots for the same provider account, so rotating after the provider declares the
account exhausted only repeats a paid-provider failure and can multiply calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

T = TypeVar("T")
TERMINAL_PROVIDER_CODES = ("OUT_OF_USAGE_CREDITS",)


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


def is_terminal_odds_failure(value: object) -> bool:
    """Return True only for provider states that are terminal across key slots."""
    text = str(value)
    return any(code in text for code in TERMINAL_PROVIDER_CODES)


def fetch_with_key_failover(keys: Iterable[str], fetcher: Callable[[str], T]) -> OddsKeyringResult[T]:
    clean = _clean_keys(keys)
    failures: list[OddsKeyFailure] = []
    terminal = False
    for slot, key in enumerate(clean, start=1):
        try:
            return OddsKeyringResult(fetcher(key), slot, tuple(failures))
        except Exception as exc:
            # Never include the credential itself in diagnostics.
            failures.append(OddsKeyFailure(slot, f"{type(exc).__name__}: {exc}"))
            if is_terminal_odds_failure(exc):
                terminal = True
                break
    summary = "; ".join(f"slot={x.key_slot}:{x.reason}" for x in failures)
    prefix = "ODDS_API_TERMINAL_FAILURE" if terminal else "ODDS_API_ALL_KEYS_FAILED"
    raise OddsKeyringError(f"{prefix}: {summary}")
