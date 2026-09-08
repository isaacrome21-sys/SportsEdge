"""Ordered, secret-safe failover for The Odds API credentials.

Keys are never logged or returned. A fetch attempt either returns a complete
provider snapshot or raises; failures are recorded only by 1-based key slot and
exception class/message. Account-level quota exhaustion is terminal for the whole
keyring; key-level/transient failures may advance to the next credential.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

T = TypeVar("T")

ACCOUNT_TERMINAL_PROVIDER_CODES = frozenset({"OUT_OF_USAGE_CREDITS"})


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


def _account_terminal_provider_code(exc: Exception) -> str | None:
    """Return a provider code only when rotating keys cannot change the outcome.

    The native Odds API source already preserves the provider error code in the
    exception text. The attribute check also supports structured provider errors
    without coupling this generic keyring to a specific source module.
    """
    value = getattr(exc, "provider_code", None)
    if value is not None:
        code = str(value).strip().upper()
        if code in ACCOUNT_TERMINAL_PROVIDER_CODES:
            return code
    rendered = str(exc).upper()
    for code in ACCOUNT_TERMINAL_PROVIDER_CODES:
        if code in rendered:
            return code
    return None


def fetch_with_key_failover(keys: Iterable[str], fetcher: Callable[[str], T]) -> OddsKeyringResult[T]:
    clean = _clean_keys(keys)
    failures: list[OddsKeyFailure] = []
    for slot, key in enumerate(clean, start=1):
        try:
            return OddsKeyringResult(fetcher(key), slot, tuple(failures))
        except Exception as exc:
            # Never include the credential itself in diagnostics.
            failures.append(OddsKeyFailure(slot, f"{type(exc).__name__}: {exc}"))
            account_terminal = _account_terminal_provider_code(exc)
            if account_terminal is not None:
                summary = "; ".join(f"slot={x.key_slot}:{x.reason}" for x in failures)
                raise OddsKeyringError(
                    f"ODDS_API_ALL_KEYS_FAILED: account_terminal={account_terminal}; {summary}"
                ) from exc
    summary = "; ".join(f"slot={x.key_slot}:{x.reason}" for x in failures)
    raise OddsKeyringError(f"ODDS_API_ALL_KEYS_FAILED: {summary}")
