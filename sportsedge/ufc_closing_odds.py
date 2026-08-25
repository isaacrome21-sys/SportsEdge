"""Verified historical UFC closing-line ingestion.

This module is deliberately provider-specific. SportsEdge only calls a historical
price "closing" when it came from The Odds API historical MMA endpoint and the
snapshot timestamp is at or before the fight commence time. Generic historic
price datasets are not promoted to closing-line evidence.

The archive format is intentionally simple JSON so evidence can be persisted and
audited independently of model training.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping, Sequence

from .ufc_source import normalize_name

ARCHIVE_SCHEMA_VERSION = 1
PROVIDER = "The Odds API"
SOURCE = "the_odds_api_historical"
SPORT_KEY = "mma_mixed_martial_arts"
PROVENANCE_DOC = "https://the-odds-api.com/historical-odds-data/"


class UFCClosingOddsError(ValueError):
    pass


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            raise UFCClosingOddsError("UFC_CLOSING_TIMESTAMP_MISSING")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise UFCClosingOddsError(
                f"UFC_CLOSING_TIMESTAMP_INVALID value={value!r}"
            ) from exc
    if dt.tzinfo is None:
        raise UFCClosingOddsError("UFC_CLOSING_TIMESTAMP_NAIVE")
    return dt.astimezone(timezone.utc)


def _american_to_implied(odds: int) -> float:
    value = int(odds)
    if value == 0 or -100 < value < 100:
        raise UFCClosingOddsError(f"UFC_CLOSING_AMERICAN_ODDS_INVALID odds={value}")
    if value > 0:
        return 100.0 / (value + 100.0)
    return (-value) / ((-value) + 100.0)


def no_vig_probability_a(odds_a: int, odds_b: int) -> float:
    pa = _american_to_implied(odds_a)
    pb = _american_to_implied(odds_b)
    total = pa + pb
    if total <= 0:
        raise UFCClosingOddsError("UFC_CLOSING_NO_VIG_INVALID")
    return pa / total


@dataclass(frozen=True)
class ClosingQuote:
    event_id: str
    snapshot_time: datetime
    commence_time: datetime
    bookmaker: str
    fighter_a: str
    fighter_b: str
    odds_a: int
    odds_b: int

    @classmethod
    def from_mapping(cls, row: Mapping[str, object]) -> "ClosingQuote":
        return cls(
            event_id=str(row.get("event_id") or "").strip(),
            snapshot_time=_utc(str(row.get("snapshot_time") or "")),
            commence_time=_utc(str(row.get("commence_time") or "")),
            bookmaker=str(row.get("bookmaker") or "").strip().lower(),
            fighter_a=str(row.get("fighter_a") or "").strip(),
            fighter_b=str(row.get("fighter_b") or "").strip(),
            odds_a=int(row.get("odds_a")),
            odds_b=int(row.get("odds_b")),
        )

    @property
    def lag_seconds(self) -> float:
        return (self.commence_time - self.snapshot_time).total_seconds()

    @property
    def pair_key(self) -> frozenset[str]:
        return frozenset((normalize_name(self.fighter_a), normalize_name(self.fighter_b)))

    def probability_for(self, fighter: str) -> float:
        p_a = no_vig_probability_a(self.odds_a, self.odds_b)
        key = normalize_name(fighter)
        if key == normalize_name(self.fighter_a):
            return p_a
        if key == normalize_name(self.fighter_b):
            return 1.0 - p_a
        raise UFCClosingOddsError(
            f"UFC_CLOSING_FIGHTER_MISMATCH fighter={fighter!r} "
            f"pair={self.fighter_a!r}/{self.fighter_b!r}"
        )


@dataclass(frozen=True)
class ClosingMatch:
    probability_a: float
    bookmakers: tuple[str, ...]
    quote_count: int
    latest_snapshot_time: str
    commence_time: str
    max_lag_seconds: float
    event_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "probability_a": self.probability_a,
            "bookmakers": list(self.bookmakers),
            "quote_count": self.quote_count,
            "latest_snapshot_time": self.latest_snapshot_time,
            "commence_time": self.commence_time,
            "max_lag_seconds": self.max_lag_seconds,
            "event_ids": list(self.event_ids),
        }


def quote_is_valid_closing(
    quote: ClosingQuote,
    *,
    max_lag_seconds: int = 900,
) -> bool:
    if not quote.event_id or not quote.bookmaker or not quote.fighter_a or not quote.fighter_b:
        return False
    if len(quote.pair_key) != 2:
        return False
    if quote.snapshot_time > quote.commence_time:
        return False
    if quote.lag_seconds < 0 or quote.lag_seconds > max_lag_seconds:
        return False
    try:
        no_vig_probability_a(quote.odds_a, quote.odds_b)
    except UFCClosingOddsError:
        return False
    return True


def archive_provenance_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if int(payload.get("schema_version") or 0) != ARCHIVE_SCHEMA_VERSION:
        errors.append("CLOSING_ARCHIVE_SCHEMA_INVALID")
    if str(payload.get("provider") or "") != PROVIDER:
        errors.append("CLOSING_PROVIDER_UNVERIFIED")
    if str(payload.get("source") or "") != SOURCE:
        errors.append("CLOSING_SOURCE_UNVERIFIED")
    if str(payload.get("sport_key") or "") != SPORT_KEY:
        errors.append("CLOSING_SPORT_KEY_INVALID")
    if str(payload.get("provenance_doc") or "") != PROVENANCE_DOC:
        errors.append("CLOSING_PROVENANCE_DOC_INVALID")
    generator = str(payload.get("generated_by") or "")
    if generator != "SportsEdge fetch_ufc_historical_closing_odds.py":
        errors.append("CLOSING_GENERATOR_UNVERIFIED")
    return errors


def load_archive(
    path: str | Path,
    *,
    max_lag_seconds: int = 900,
) -> tuple[dict[str, object], list[ClosingQuote], list[str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise UFCClosingOddsError("UFC_CLOSING_ARCHIVE_INVALID")

    errors = archive_provenance_errors(payload)
    rows = payload.get("quotes")
    if not isinstance(rows, list):
        raise UFCClosingOddsError("UFC_CLOSING_QUOTES_INVALID")

    quotes: list[ClosingQuote] = []
    malformed = 0
    invalid_closing = 0
    for row in rows:
        if not isinstance(row, Mapping):
            malformed += 1
            continue
        try:
            quote = ClosingQuote.from_mapping(row)
        except (TypeError, ValueError, UFCClosingOddsError):
            malformed += 1
            continue
        if not quote_is_valid_closing(quote, max_lag_seconds=max_lag_seconds):
            invalid_closing += 1
            continue
        quotes.append(quote)

    if malformed:
        errors.append(f"CLOSING_ROWS_MALFORMED:{malformed}")
    if invalid_closing:
        errors.append(f"CLOSING_ROWS_NOT_PRECOMMENCE:{invalid_closing}")
    if not quotes:
        errors.append("CLOSING_QUOTES_EMPTY")

    return payload, quotes, errors


def _fight_day(meta: Mapping[str, object]) -> date:
    text = str(meta.get("fight_date") or "")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise UFCClosingOddsError(
            f"UFC_CLOSING_FIGHT_DATE_INVALID value={text!r}"
        ) from exc


def match_closing_market(
    meta: Mapping[str, object],
    quotes: Sequence[ClosingQuote],
    *,
    min_bookmakers: int = 2,
    date_tolerance_days: int = 1,
    max_lag_seconds: int = 900,
) -> ClosingMatch | None:
    fighter_a = str(meta.get("fighter_a") or "")
    fighter_b = str(meta.get("fighter_b") or "")
    if not fighter_a or not fighter_b:
        return None
    pair = frozenset((normalize_name(fighter_a), normalize_name(fighter_b)))
    fight_day = _fight_day(meta)

    candidates = [
        quote
        for quote in quotes
        if quote_is_valid_closing(quote, max_lag_seconds=max_lag_seconds)
        and quote.pair_key == pair
        and abs((quote.commence_time.date() - fight_day).days) <= date_tolerance_days
    ]
    if not candidates:
        return None

    # Keep the latest valid pre-commence quote per bookmaker. An archive may
    # contain several snapshots from the same book.
    by_book: dict[str, ClosingQuote] = {}
    for quote in candidates:
        current = by_book.get(quote.bookmaker)
        if current is None or quote.snapshot_time > current.snapshot_time:
            by_book[quote.bookmaker] = quote

    if len(by_book) < int(min_bookmakers):
        return None

    selected = sorted(by_book.values(), key=lambda q: q.bookmaker)
    probs = [quote.probability_for(fighter_a) for quote in selected]
    latest = max(quote.snapshot_time for quote in selected)
    # Commence times should agree for the same provider event. Persist the
    # earliest to remain conservative if provider rows disagree slightly.
    commence = min(quote.commence_time for quote in selected)
    return ClosingMatch(
        probability_a=mean(probs),
        bookmakers=tuple(quote.bookmaker for quote in selected),
        quote_count=len(selected),
        latest_snapshot_time=latest.isoformat(),
        commence_time=commence.isoformat(),
        max_lag_seconds=max(quote.lag_seconds for quote in selected),
        event_ids=tuple(sorted({quote.event_id for quote in selected})),
    )


def enrich_metadata_with_closing_market(
    metadata: Iterable[Mapping[str, object]],
    quotes: Sequence[ClosingQuote],
    *,
    min_bookmakers: int = 2,
    date_tolerance_days: int = 1,
    max_lag_seconds: int = 900,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    matched = 0
    book_counts: list[int] = []
    for meta in metadata:
        row = dict(meta)
        match = match_closing_market(
            row,
            quotes,
            min_bookmakers=min_bookmakers,
            date_tolerance_days=date_tolerance_days,
            max_lag_seconds=max_lag_seconds,
        )
        if match is not None:
            row["market_probability_a"] = match.probability_a
            row["closing_market"] = match.as_dict()
            matched += 1
            book_counts.append(match.quote_count)
        rows.append(row)

    total = len(rows)
    coverage = 0.0 if total == 0 else matched / total
    return rows, {
        "rows": total,
        "matched": matched,
        "coverage": coverage,
        "min_bookmakers": int(min_bookmakers),
        "mean_bookmakers": 0.0 if not book_counts else mean(book_counts),
    }


def closing_archive_template(*, generated_at: datetime | None = None) -> dict[str, object]:
    now = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "provider": PROVIDER,
        "source": SOURCE,
        "sport_key": SPORT_KEY,
        "provenance_doc": PROVENANCE_DOC,
        "generated_by": "SportsEdge fetch_ufc_historical_closing_odds.py",
        "generated_at": now.isoformat(),
        "quotes": [],
    }
