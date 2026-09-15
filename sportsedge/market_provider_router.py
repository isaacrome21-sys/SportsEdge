"""Provider-neutral quote routing for book-agnostic game-market consumers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .market_provider_contract import ProviderContractError, admit_quote


@dataclass(frozen=True)
class RoutedQuotes:
    quotes: tuple[Mapping[str, Any], ...]
    rejected: tuple[Mapping[str, Any], ...]


def route_quotes(
    rows: Iterable[Mapping[str, Any]],
    *,
    required_book: str | None = None,
    now=None,
) -> RoutedQuotes:
    """Admit only quotes the source contract itself can satisfy."""
    accepted = []
    rejected = []
    for row in rows:
        try:
            admission = admit_quote(row, required_book=required_book, now=now)
            accepted.append({
                **dict(row),
                "provider_contract": {
                    "provider": admission.provider,
                    "market": admission.market,
                    "sportsbook": admission.sportsbook,
                    "exact_book_satisfied": admission.exact_book_satisfied,
                    "ttl_seconds": admission.ttl_seconds,
                },
            })
        except ProviderContractError as exc:
            rejected.append({
                "quote_provider": row.get("quote_provider"),
                "sportsbook": row.get("sportsbook"),
                "market": row.get("market"),
                "reason": str(exc),
            })
    return RoutedQuotes(tuple(accepted), tuple(rejected))


def free_first_game_quotes(
    *,
    free_fetch: Callable[[], Iterable[Mapping[str, Any]]],
    paid_fetch: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
    required_book: str | None = None,
    now=None,
) -> RoutedQuotes:
    """Use eligible free game quotes first; call paid transport only if none survive.

    This is intentionally unsuitable for frozen lanes that require a specific
    acquisition transport. Those lanes must not call this helper.
    """
    free = route_quotes(free_fetch(), required_book=required_book, now=now)
    if free.quotes or paid_fetch is None:
        return free
    paid = route_quotes(paid_fetch(), required_book=required_book, now=now)
    return RoutedQuotes(paid.quotes, free.rejected + paid.rejected)
