"""Network-free MLB quote acquisition from frozen raw The Odds API bytes.

These functions are the only supported entrypoints for paid-provider replay.
They always inject ``FrozenOddsReplayStore.open``; there is no live opener
parameter and no fallback path. Any frozen cache/manifest/hash failure is raised
rather than being downgraded to a quote-level failure row.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .game_odds_source import GameOddsSnapshot, fetch_mlb_game_quotes
from .mlb_source import GameSnapshot
from .odds_api_frozen import FrozenOddsReplayError, FrozenOddsReplayStore
from .odds_api_source import (
    DEFAULT_BOOKMAKERS,
    DEFAULT_TTL_SECONDS,
    OddsApiSnapshot,
    fetch_mlb_player_prop_quotes,
)

_REPLAY_API_KEY = "FROZEN_REPLAY_ONLY"


def _frozen_error_in_chain(exc: BaseException) -> FrozenOddsReplayError | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, FrozenOddsReplayError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _raise_if_frozen_exception(exc: BaseException) -> None:
    frozen = _frozen_error_in_chain(exc)
    if frozen is not None:
        raise FrozenOddsReplayError(str(frozen)) from exc
    # ``_get_json`` intentionally redacts arbitrary exception messages and keeps
    # only the exception class. Preserve fail-closed semantics when that wrapper
    # has already converted a replay-store error into an OddsApiSourceError.
    if "FrozenOddsReplayError" in str(exc):
        raise FrozenOddsReplayError(str(exc)) from exc


def _raise_if_frozen_transport_failed(failures: Iterable[Mapping[str, Any]]) -> None:
    for failure in failures:
        reason = str(failure.get("reason") or "")
        if "FROZEN_ODDS_" in reason or "FrozenOddsReplayError" in reason:
            raise FrozenOddsReplayError(reason)


def replay_mlb_game_quotes(
    *,
    replay_store: FrozenOddsReplayStore,
    schedule: Iterable[GameSnapshot],
    bookmakers: Iterable[str] = DEFAULT_BOOKMAKERS,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> GameOddsSnapshot:
    """Parse game-market quotes from raw private bytes with zero network path."""
    try:
        snapshot = fetch_mlb_game_quotes(
            api_key=_REPLAY_API_KEY,
            schedule=schedule,
            opener=replay_store.open,
            bookmakers=bookmakers,
            ttl_seconds=ttl_seconds,
            event_snapshot=None,
        )
    except Exception as exc:
        _raise_if_frozen_exception(exc)
        raise
    _raise_if_frozen_transport_failed(snapshot.failures)
    return snapshot


def replay_mlb_player_prop_quotes(
    *,
    replay_store: FrozenOddsReplayStore,
    schedule: Iterable[GameSnapshot],
    participant_index: Mapping[int, Mapping[str, int]],
    bookmakers: Iterable[str] = DEFAULT_BOOKMAKERS,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> OddsApiSnapshot:
    """Parse player-prop quotes from raw private bytes with zero network path."""
    try:
        snapshot = fetch_mlb_player_prop_quotes(
            api_key=_REPLAY_API_KEY,
            schedule=schedule,
            participant_index=participant_index,
            opener=replay_store.open,
            bookmakers=bookmakers,
            ttl_seconds=ttl_seconds,
            event_snapshot=None,
        )
    except Exception as exc:
        _raise_if_frozen_exception(exc)
        raise
    _raise_if_frozen_transport_failed(snapshot.failures)
    return snapshot
