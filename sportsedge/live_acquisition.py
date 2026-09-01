"""Acquisition contracts for automatic LIVE RUN IT state and market pulls.

Providers normalize into the same schema whether data came from an API, public
web source, tool, or a user-supplied screenshot/manual entry. Acquisition method
must not change downstream classification semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Protocol, Sequence

from .live_markets import LiveMarketQuote, requested_market_scope


class LiveAcquisitionError(ValueError):
    pass


@dataclass(frozen=True)
class LiveEventRef:
    sport: str
    event_id: str
    status: str  # PREGAME / LIVE / FINAL / SUSPENDED
    scheduled_start: datetime
    home_team: str
    away_team: str

    def validate(self) -> None:
        if self.sport not in {"MLB", "NFL", "CFB"}:
            raise LiveAcquisitionError("unsupported sport")
        if self.status not in {"PREGAME", "LIVE", "FINAL", "SUSPENDED"}:
            raise LiveAcquisitionError("invalid event status")
        if self.scheduled_start.tzinfo is None:
            raise LiveAcquisitionError("scheduled_start must be timezone-aware")
        if not self.event_id or not self.home_team or not self.away_team:
            raise LiveAcquisitionError("event identity is incomplete")


@dataclass(frozen=True)
class AcquisitionGap:
    event_id: str
    market: str
    field: str
    reason: str
    material: bool = True


@dataclass(frozen=True)
class LiveAcquisitionBundle:
    event: LiveEventRef
    state_payload: Mapping[str, object] | None
    state_source_as_of: datetime | None
    state_provider: str | None
    quotes: tuple[LiveMarketQuote, ...] = ()
    gaps: tuple[AcquisitionGap, ...] = ()

    @property
    def needs_manual_input(self) -> bool:
        return any(gap.material for gap in self.gaps)


class LiveSourceProvider(Protocol):
    name: str

    def fetch_state(self, event: LiveEventRef) -> tuple[Mapping[str, object], datetime] | None:
        ...

    def fetch_quotes(self, event: LiveEventRef, markets: Sequence[str]) -> Iterable[LiveMarketQuote]:
        ...


def build_live_bundle(event: LiveEventRef, providers: Sequence[LiveSourceProvider]) -> LiveAcquisitionBundle:
    """Automatic-first acquisition with exact-field DATA_GAP reporting.

    The first usable state snapshot wins. Quotes are collected across providers
    without inventing missing paired sides. No manual input is requested unless
    an exact missing field remains material after all automatic providers run.
    """
    event.validate()
    if event.status != "LIVE":
        raise LiveAcquisitionError("build_live_bundle requires a LIVE event")

    state_payload = None
    state_as_of = None
    state_provider = None
    quotes: list[LiveMarketQuote] = []

    scope = requested_market_scope(event.sport)
    for provider in providers:
        if state_payload is None:
            state = provider.fetch_state(event)
            if state is not None:
                payload, as_of = state
                if as_of.tzinfo is None:
                    raise LiveAcquisitionError("provider state timestamp must be timezone-aware")
                state_payload = dict(payload)
                state_as_of = as_of
                state_provider = provider.name
        for quote in provider.fetch_quotes(event, scope):
            quote.validate()
            if quote.event_id != event.event_id or quote.sport != event.sport:
                raise LiveAcquisitionError("provider returned quote for wrong event/sport")
            quotes.append(quote)

    gaps: list[AcquisitionGap] = []
    if state_payload is None:
        gaps.append(AcquisitionGap(event.event_id, "GAME_STATE", "state_payload", "SOURCE_UNAVAILABLE_AUTO"))

    by_market: dict[str, list[LiveMarketQuote]] = {market: [] for market in scope}
    for quote in quotes:
        by_market.setdefault(quote.market, []).append(quote)

    for market in scope:
        market_quotes = by_market.get(market, [])
        if not market_quotes:
            gaps.append(AcquisitionGap(event.event_id, market, "quote", "SOURCE_UNAVAILABLE_AUTO", material=False))
            continue
        if not any(q.active and q.paired for q in market_quotes):
            gaps.append(AcquisitionGap(event.event_id, market, "paired_price", "LIVE_QUOTE_DATA_GAP", material=False))

    return LiveAcquisitionBundle(
        event=event,
        state_payload=state_payload,
        state_source_as_of=state_as_of,
        state_provider=state_provider,
        quotes=tuple(quotes),
        gaps=tuple(gaps),
    )


def merge_manual_quote(bundle: LiveAcquisitionBundle, quote: LiveMarketQuote) -> LiveAcquisitionBundle:
    """Normalize a user-supplied quote into the same downstream evidence bundle."""
    quote.validate()
    if quote.event_id != bundle.event.event_id or quote.sport != bundle.event.sport:
        raise LiveAcquisitionError("manual quote does not match event")
    remaining = tuple(
        gap for gap in bundle.gaps
        if not (gap.market == quote.market and gap.field in {"quote", "paired_price"} and quote.paired)
    )
    return LiveAcquisitionBundle(
        event=bundle.event,
        state_payload=bundle.state_payload,
        state_source_as_of=bundle.state_source_as_of,
        state_provider=bundle.state_provider,
        quotes=bundle.quotes + (quote,),
        gaps=remaining,
    )
