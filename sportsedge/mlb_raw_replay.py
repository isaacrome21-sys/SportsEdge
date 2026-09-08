"""Replay MLB Odds API acquisition from verified frozen raw response bytes.

This execution path is intentionally separate from live acquisition and has no
API-key, opener, URL, retry, or cache-fallback argument. Missing frozen bytes are
fatal to replay.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .game_odds_source import GameOddsSnapshot, parse_game_event_odds
from .mlb_quote_attestation import stamp_the_odds_api_quote
from .mlb_source import GameSnapshot
from .odds_api_replay import FrozenOddsApiReplay, OddsApiReplayError
from .odds_api_source import (
    DEFAULT_TTL_SECONDS,
    OddsApiSnapshot,
    OddsApiSourceError,
    bind_provider_event,
    parse_event_odds,
)


def replay_mlb_game_quotes(
    *,
    replay: FrozenOddsApiReplay,
    schedule: Iterable[GameSnapshot],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    response_label: str = "game-markets",
) -> GameOddsSnapshot:
    """Parse and bind frozen featured-game market bytes with no network path."""
    payload = replay.read_json(response_label)
    if not isinstance(payload, list):
        raise OddsApiReplayError("ODDS_REPLAY_GAME_MARKETS_RESPONSE_NOT_LIST")
    games = list(schedule)
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in payload:
        if not isinstance(event, Mapping):
            failures.append({"reason": "ODDS_EVENT_MALFORMED", "provider_event_id": ""})
            continue
        try:
            game = bind_provider_event(event, games)
            snapshot = parse_game_event_odds(event, game=game, ttl_seconds=ttl_seconds)
            quotes.extend(snapshot.quotes)
            failures.extend(snapshot.failures)
        except Exception as exc:
            failures.append({
                "reason": str(exc),
                "provider_event_id": str(event.get("id") or ""),
            })
    return GameOddsSnapshot(tuple(quotes), tuple(failures))


def replay_mlb_player_prop_quotes(
    *,
    replay: FrozenOddsApiReplay,
    schedule: Iterable[GameSnapshot],
    participant_index: Mapping[int, Mapping[str, int]],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    events_label: str = "events",
) -> OddsApiSnapshot:
    """Parse frozen event-list and per-event odds bytes with no live fallback.

    Per-event raw odds responses are addressed as ``event:<provider_event_id>``.
    Any missing entry or hash mismatch raises ``OddsApiReplayError`` and aborts the
    replay rather than silently returning a partial cache hit.
    """
    events = replay.read_json(events_label)
    if not isinstance(events, list):
        raise OddsApiReplayError("ODDS_REPLAY_EVENTS_RESPONSE_NOT_LIST")
    games = list(schedule)
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            failures.append({"reason": "ODDS_EVENT_MALFORMED", "provider_event_id": ""})
            continue
        try:
            game = bind_provider_event(event, games)
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                raise OddsApiSourceError("ODDS_EVENT_ID_MISSING")
            raw_event_odds = replay.read_json(f"event:{event_id}")
            if not isinstance(raw_event_odds, Mapping):
                raise OddsApiReplayError(f"ODDS_REPLAY_EVENT_ODDS_NOT_MAPPING:{event_id}")
            snapshot = parse_event_odds(
                raw_event_odds,
                game=game,
                participant_index=participant_index,
                ttl_seconds=ttl_seconds,
            )
            for quote in snapshot.quotes:
                quotes.append(stamp_the_odds_api_quote(quote, provider_event=event, game=game))
            failures.extend(snapshot.failures)
        except OddsApiReplayError:
            # A frozen-byte miss/hash failure invalidates the entire evidence run.
            raise
        except Exception as exc:
            failures.append({
                "reason": str(exc),
                "provider_event_id": str(event.get("id") or ""),
            })
    return OddsApiSnapshot(tuple(quotes), tuple(failures))
