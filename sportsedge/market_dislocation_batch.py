"""Batch execution for the market-only dislocation scanner.

The batch lane scans executable target-book offers against independent reference
books. It never feeds its output into Model_P.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from .market_dislocation import MarketDislocation, scan_market_dislocation


class MarketDislocationBatchError(ValueError):
    pass


@dataclass(frozen=True)
class MarketDislocationBatch:
    results: tuple[MarketDislocation, ...]
    failures: tuple[dict[str, Any], ...]
    candidate_books: tuple[str, ...]
    reference_books: tuple[str, ...]


def scan_dislocation_snapshot(
    quote_snapshot: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
    candidate_books: Iterable[str],
    reference_books: Iterable[str],
    min_reference_books: int = 2,
    max_age_seconds: float = 120.0,
    max_cross_book_skew_seconds: float = 60.0,
    max_reference_probability_spread: float = 0.04,
    min_probability_edge: float = 0.01,
    min_conditional_ev: float = 0.01,
) -> MarketDislocationBatch:
    rows = list(quote_snapshot)
    targets = tuple(sorted({str(x).strip() for x in candidate_books if str(x).strip()}))
    refs = tuple(sorted({str(x).strip() for x in reference_books if str(x).strip()}))
    if not targets:
        raise MarketDislocationBatchError("CANDIDATE_BOOKS_REQUIRED")
    if not refs:
        raise MarketDislocationBatchError("REFERENCE_BOOKS_REQUIRED")
    overlap = set(targets).intersection(refs)
    if overlap:
        raise MarketDislocationBatchError(f"CANDIDATE_REFERENCE_BOOK_OVERLAP:{sorted(overlap)}")

    results: list[MarketDislocation] = []
    failures: list[dict[str, Any]] = []
    seen_candidates: set[tuple[Any, ...]] = set()

    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            failures.append({"source_index": index, "reason": "CANDIDATE_ROW_NOT_MAPPING"})
            continue
        book = str(raw.get("book_key") or "").strip()
        if book not in targets:
            continue
        key = (
            str(raw.get("event_id") or ""), raw.get("game_number"),
            str(raw.get("period") or ""), str(raw.get("market") or ""),
            str(raw.get("entity_id") or ""), repr(raw.get("line")),
            str(raw.get("side") or ""), book, raw.get("american_odds"),
            raw.get("retrieved_at"), raw.get("is_alternate"),
        )
        if key in seen_candidates:
            failures.append({"source_index": index, "reason": "DUPLICATE_CANDIDATE_OFFER"})
            continue
        seen_candidates.add(key)
        try:
            result = scan_market_dislocation(
                raw,
                rows,
                as_of=as_of,
                reference_books=refs,
                min_reference_books=min_reference_books,
                max_age_seconds=max_age_seconds,
                max_cross_book_skew_seconds=max_cross_book_skew_seconds,
                max_reference_probability_spread=max_reference_probability_spread,
                min_probability_edge=min_probability_edge,
                min_conditional_ev=min_conditional_ev,
            )
            results.append(result)
        except Exception as exc:
            failures.append({
                "source_index": index,
                "book_key": book,
                "reason": f"{type(exc).__name__}: {exc}",
            })

    return MarketDislocationBatch(tuple(results), tuple(failures), targets, refs)
