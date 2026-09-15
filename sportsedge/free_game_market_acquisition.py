"""Free-first MLB game-market acquisition for non-frozen consumers."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Mapping, Any
from urllib.request import urlopen

from .espn_game_odds_source import fetch_espn_mlb_game_quotes
from .market_provider_router import RoutedQuotes, free_first_game_quotes
from .mlb_source import GameSnapshot


def acquire_mlb_game_markets_free_first(
    *,
    schedule: Iterable[GameSnapshot],
    opener: Callable = urlopen,
    now: datetime | None = None,
    required_book: str | None = None,
    paid_fetch: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
) -> RoutedQuotes:
    """Acquire ML/RL/totals from ESPN first for book-agnostic consumers.

    If `required_book` is supplied, ESPN is eligible only when its own payload
    explicitly identifies that book. A paid callback is optional and is invoked
    only when no free quote survives the provider contract.
    """
    games = tuple(schedule)

    def free_fetch():
        return fetch_espn_mlb_game_quotes(
            schedule=games,
            opener=opener,
            now=now,
            ttl_seconds=60,
        ).quotes

    return free_first_game_quotes(
        free_fetch=free_fetch,
        paid_fetch=paid_fetch,
        required_book=required_book,
        now=now,
    )
