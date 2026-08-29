"""Historical CFB market archive contract for benchmark, CLV and replay.

A single closing line is sufficient for a closing-market benchmark but NOT sufficient
for CLV. CLV requires a decision-time two-sided quote for the exact original contract
plus a synchronized closing reference for that same contract (or a frozen, separately
validated repricing artifact). This module makes that distinction explicit so sparse
CFBD line history cannot be silently treated as a full odds path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping


class CFBHistoricalMarketError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBHistoricalMarketError(f"{field}:TIMESTAMP_REQUIRED")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBHistoricalMarketError(f"{field}:ISO8601_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBHistoricalMarketError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBHistoricalMarketError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBHistoricalMarketError(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class HistoricalQuote:
    quote_id: str
    game_id: str
    season: int
    market: str
    side: str
    line: float | None
    american_odds: float
    book: str
    provider: str
    captured_ts: str
    source_artifact_id: str
    is_closing: bool = False

    def validate(self) -> "HistoricalQuote":
        if not all((self.quote_id, self.game_id, self.book, self.provider, self.source_artifact_id)):
            raise CFBHistoricalMarketError("HISTORICAL_QUOTE_IDENTITY_REQUIRED")
        if self.market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            raise CFBHistoricalMarketError("HISTORICAL_QUOTE_MARKET_INVALID")
        allowed = {"HOME", "AWAY"} if self.market in {"MONEYLINE", "SPREAD"} else {"OVER", "UNDER"}
        if self.side not in allowed:
            raise CFBHistoricalMarketError("HISTORICAL_QUOTE_SIDE_INVALID")
        if self.market == "MONEYLINE":
            if self.line not in {None, 0.0}:
                raise CFBHistoricalMarketError("HISTORICAL_MONEYLINE_LINE_INVALID")
        elif self.line is None:
            raise CFBHistoricalMarketError("HISTORICAL_LINE_REQUIRED")
        odds = _finite(self.american_odds, "american_odds")
        if -100.0 < odds < 100.0:
            raise CFBHistoricalMarketError("HISTORICAL_AMERICAN_ODDS_INVALID")
        _utc(self.captured_ts, "captured_ts")
        if isinstance(self.is_closing, bool) is False:
            raise CFBHistoricalMarketError("HISTORICAL_IS_CLOSING_BOOL_REQUIRED")
        return self


@dataclass(frozen=True)
class HistoricalMarketArchive:
    archive_id: str
    quotes: tuple[HistoricalQuote, ...]
    source_ids: tuple[str, ...]
    has_intraday_path: bool
    has_two_sided_prices: bool

    def validate(self) -> "HistoricalMarketArchive":
        if not self.archive_id or not self.source_ids:
            raise CFBHistoricalMarketError("HISTORICAL_ARCHIVE_IDENTITY_REQUIRED")
        if not self.quotes:
            raise CFBHistoricalMarketError("HISTORICAL_ARCHIVE_EMPTY")
        for quote in self.quotes:
            quote.validate()
        ids = [quote.quote_id for quote in self.quotes]
        if len(ids) != len(set(ids)):
            raise CFBHistoricalMarketError("HISTORICAL_QUOTE_ID_DUPLICATE")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "archive_id": self.archive_id,
            "quotes": [asdict(quote) for quote in self.quotes],
            "source_ids": list(self.source_ids),
            "has_intraday_path": self.has_intraday_path,
            "has_two_sided_prices": self.has_two_sided_prices,
        }

    def content_hash(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()

    @property
    def clv_capable(self) -> bool:
        self.validate()
        return bool(self.has_intraday_path and self.has_two_sided_prices)

    def require_clv_capable(self) -> "HistoricalMarketArchive":
        if not self.clv_capable:
            missing = []
            if not self.has_intraday_path:
                missing.append("INTRADAY_DECISION_PATH")
            if not self.has_two_sided_prices:
                missing.append("TWO_SIDED_PRICES")
            raise CFBHistoricalMarketError("HISTORICAL_ARCHIVE_NOT_CLV_CAPABLE:" + ",".join(missing))
        return self


def audit_historical_market_rows(rows: Iterable[HistoricalQuote | Mapping[str, Any]], *, archive_id: str) -> HistoricalMarketArchive:
    quotes: list[HistoricalQuote] = []
    for source in rows:
        if isinstance(source, HistoricalQuote):
            quote = source.validate()
        else:
            row = dict(source)
            quote = HistoricalQuote(
                quote_id=str(row.get("quote_id") or "").strip(),
                game_id=str(row.get("game_id") or "").strip(),
                season=int(row.get("season")),
                market=str(row.get("market") or "").strip().upper(),
                side=str(row.get("side") or "").strip().upper(),
                line=None if row.get("line") is None else float(row.get("line")),
                american_odds=float(row.get("american_odds")),
                book=str(row.get("book") or "").strip().upper(),
                provider=str(row.get("provider") or "").strip().upper(),
                captured_ts=str(row.get("captured_ts") or "").strip(),
                source_artifact_id=str(row.get("source_artifact_id") or "").strip(),
                is_closing=row.get("is_closing") is True,
            ).validate()
        quotes.append(quote)
    if not quotes:
        raise CFBHistoricalMarketError("HISTORICAL_ARCHIVE_EMPTY")

    groups: dict[tuple[str, str, str, float | None, str], set[str]] = {}
    timestamps: dict[tuple[str, str, str, float | None], set[str]] = {}
    for quote in quotes:
        groups.setdefault((quote.game_id, quote.market, quote.book, quote.line, quote.captured_ts), set()).add(quote.side)
        timestamps.setdefault((quote.game_id, quote.market, quote.book, quote.line), set()).add(quote.captured_ts)
    two_sided = any(
        sides in ({"HOME", "AWAY"}, {"OVER", "UNDER"})
        for sides in groups.values()
    )
    intraday = any(len(values) >= 2 for values in timestamps.values())
    return HistoricalMarketArchive(
        archive_id=str(archive_id),
        quotes=tuple(quotes),
        source_ids=tuple(sorted({quote.source_artifact_id for quote in quotes})),
        has_intraday_path=intraday,
        has_two_sided_prices=two_sided,
    ).validate()


def declare_closing_only_archive(
    *,
    archive_id: str,
    rows: Iterable[HistoricalQuote | Mapping[str, Any]],
) -> HistoricalMarketArchive:
    """Explicitly mark a sparse closing-line source as non-CLV-capable.

    This is the correct treatment for data sources that expose closing lines without a
    timestamped decision-time path. They may still benchmark held-out probabilities at
    close; they cannot satisfy the paired historical price / CLV Truth Gate criteria.
    """

    audited = audit_historical_market_rows(rows, archive_id=archive_id)
    return HistoricalMarketArchive(
        archive_id=audited.archive_id,
        quotes=audited.quotes,
        source_ids=audited.source_ids,
        has_intraday_path=False,
        has_two_sided_prices=audited.has_two_sided_prices,
    ).validate()
