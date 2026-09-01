"""Live market registry and normalized quote contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


COMMON_LIVE_MARKETS = frozenset({
    "MONEYLINE",
    "SPREAD",
    "TOTAL",
    "TEAM_TOTAL",
    "PLAYER_PROP",
})

SPORT_LIVE_MARKETS = {
    "NFL": COMMON_LIVE_MARKETS | {
        "1H_MONEYLINE", "1H_SPREAD", "1H_TOTAL", "2H_MONEYLINE", "2H_SPREAD", "2H_TOTAL",
        "QUARTER_MONEYLINE", "QUARTER_SPREAD", "QUARTER_TOTAL", "ALT_SPREAD", "ALT_TOTAL",
    },
    "CFB": COMMON_LIVE_MARKETS | {
        "1H_MONEYLINE", "1H_SPREAD", "1H_TOTAL", "2H_MONEYLINE", "2H_SPREAD", "2H_TOTAL",
        "QUARTER_MONEYLINE", "QUARTER_SPREAD", "QUARTER_TOTAL", "ALT_SPREAD", "ALT_TOTAL",
    },
    "MLB": COMMON_LIVE_MARKETS | {
        "RUN_LINE", "ALT_RUN_LINE", "ALT_TOTAL", "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTAL",
        "INNING_MONEYLINE", "INNING_TOTAL", "NRFI_YRFI", "BATTER_PROP", "PITCHER_PROP",
    },
}


class LiveMarketError(ValueError):
    pass


@dataclass(frozen=True)
class LiveMarketQuote:
    sport: str
    event_id: str
    book: str
    market: str
    contract_key: str
    focal_selection: str
    opposite_selection: str
    focal_odds: float | None
    opposite_odds: float | None
    source_as_of: datetime
    retrieved_at: datetime
    active: bool
    provider: str

    def validate(self) -> None:
        if self.sport not in SPORT_LIVE_MARKETS:
            raise LiveMarketError("unsupported sport")
        if self.market not in SPORT_LIVE_MARKETS[self.sport]:
            raise LiveMarketError(f"unsupported {self.sport} live market: {self.market}")
        if not all((self.event_id, self.book, self.contract_key, self.focal_selection, self.opposite_selection, self.provider)):
            raise LiveMarketError("quote identity/provenance fields are required")
        if self.source_as_of.tzinfo is None or self.retrieved_at.tzinfo is None:
            raise LiveMarketError("quote timestamps must be timezone-aware")
        if self.source_as_of > self.retrieved_at:
            raise LiveMarketError("quote source_as_of cannot be after retrieved_at")
        for odds in (self.focal_odds, self.opposite_odds):
            if odds is not None and -100 < float(odds) < 100:
                raise LiveMarketError("invalid American odds")

    @property
    def paired(self) -> bool:
        return self.focal_odds is not None and self.opposite_odds is not None

    @property
    def governance_status(self) -> str:
        self.validate()
        if not self.active:
            return "MARKET_INACTIVE"
        if not self.paired:
            return "LIVE_QUOTE_DATA_GAP"
        return "PAIRED_QUOTE_READY"


def requested_market_scope(sport: str) -> tuple[str, ...]:
    try:
        return tuple(sorted(SPORT_LIVE_MARKETS[sport]))
    except KeyError as exc:
        raise LiveMarketError(f"unsupported sport: {sport}") from exc


def quote_gaps(quotes: Iterable[LiveMarketQuote]) -> list[LiveMarketQuote]:
    gaps = []
    for quote in quotes:
        quote.validate()
        if quote.governance_status == "LIVE_QUOTE_DATA_GAP":
            gaps.append(quote)
    return gaps
