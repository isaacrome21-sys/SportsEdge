"""Market-only stale-price / dislocation scanner for MLB.

This module never creates or consumes Model_P. Every candidate and reference
quote is first checked against the independent official LiveGame context through
the production MLB v1.2.2 quote-binding boundary. Reference probabilities are
then derived only from valid paired sportsbook prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import median
from typing import Any, Iterable, Mapping

from .devig import DevigError, multiplicative_devig
from .mlb_binding_runtime import quote_binding_row
from .mlb_market_binding import INTEGER_PUSHABLE, MARKET_BINDINGS, NO_THRESHOLD, validate_quote_binding
from .truth_gate import american_to_decimal


class MarketDislocationError(ValueError):
    pass


PROHIBITED_MODEL_KEYS = frozenset({
    "model_p", "model_probability", "sportsedge_probability", "model_edge",
    "model_ev", "fair_model_probability",
})


@dataclass(frozen=True)
class MarketDislocation:
    status: str
    reason: str
    event_id: str
    market: str
    side: str
    line: float | None
    candidate_book: str
    candidate_odds: int
    candidate_raw_implied: float
    reference_fair_probability: float | None
    reference_books: tuple[str, ...]
    reference_count: int
    probability_edge: float | None
    conditional_ev_per_decision: float | None
    exact_market_ev_per_dollar: float | None
    push_mass_required_for_exact_ev: bool


def _aware(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MarketDislocationError(f"{field}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _reject_model_contamination(row: Mapping[str, Any]) -> None:
    bad = PROHIBITED_MODEL_KEYS.intersection(map(str, row.keys()))
    if bad:
        raise MarketDislocationError(f"MODEL_DATA_PROHIBITED_IN_MARKET_SCANNER:{sorted(bad)}")


def _validated(
    row: Mapping[str, Any],
    *,
    game: Any,
    as_of: datetime,
    max_age_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _reject_model_contamination(row)
    quote = dict(row)
    binding = quote_binding_row(game=game, quote=quote)
    validate_quote_binding(binding)
    retrieved = _aware(quote.get("retrieved_at"), "retrieved_at")
    if retrieved > as_of:
        raise MarketDislocationError("QUOTE_FROM_FUTURE")
    age = (as_of - retrieved).total_seconds()
    if age > max_age_seconds:
        raise MarketDislocationError(f"QUOTE_STALE:{age:.1f}>{max_age_seconds}")
    return quote, binding


def _outcome_key(binding: Mapping[str, Any]) -> tuple[Any, ...]:
    market = str(binding["market_id"])
    spec = MARKET_BINDINGS[market]
    if "team_id" in binding:
        subject: Any = str(binding["team_id"])
    elif "entity_id" in binding:
        subject = str(binding["entity_id"])
    elif "entity_ids" in binding:
        subject = tuple(map(str, binding.get("entity_ids") or ()))
    else:
        subject = "GAME"
    line = None if spec.threshold_semantics == NO_THRESHOLD else float(binding["line"])
    return (
        str(binding["event_id"]), int(binding["game_number"]), str(binding["period"]),
        market, str(binding["side"]), subject, line,
    )


def _pair_for(
    side_quote: Mapping[str, Any],
    book_rows: list[tuple[dict[str, Any], dict[str, Any]]],
) -> Mapping[str, Any]:
    matches: list[Mapping[str, Any]] = []
    for other, _ in book_rows:
        if other is side_quote or dict(other) == dict(side_quote):
            continue
        try:
            multiplicative_devig(side_quote, other)
        except DevigError:
            continue
        matches.append(other)
    if len(matches) != 1:
        raise MarketDislocationError(f"REFERENCE_PAIR_AMBIGUOUS_OR_MISSING:{len(matches)}")
    return matches[0]


def scan_market_dislocation(
    candidate: Mapping[str, Any],
    quote_snapshot: Iterable[Mapping[str, Any]],
    *,
    game: Any,
    as_of: datetime,
    reference_books: Iterable[str] | None = None,
    min_reference_books: int = 2,
    max_age_seconds: float = 120.0,
    max_cross_book_skew_seconds: float = 60.0,
    min_probability_edge: float = 0.01,
    min_conditional_ev: float = 0.01,
) -> MarketDislocation:
    """Compare an executable quote with independent de-vigged reference books.

    The result is market context only. It is not Model_P, cannot promote a market,
    and must never be fed back into predictive features.
    """
    now = _aware(as_of, "as_of")
    if min_reference_books < 1:
        raise MarketDislocationError("MIN_REFERENCE_BOOKS_INVALID")
    if not isfinite(float(min_probability_edge)) or not isfinite(float(min_conditional_ev)):
        raise MarketDislocationError("EDGE_THRESHOLD_INVALID")

    cand, cand_binding = _validated(candidate, game=game, as_of=now, max_age_seconds=max_age_seconds)
    cand_key = _outcome_key(cand_binding)
    candidate_book = str(cand_binding["book_key"])
    allowed = None if reference_books is None else {str(x) for x in reference_books if str(x)}

    by_book: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for raw in quote_snapshot:
        try:
            quote, binding = _validated(raw, game=game, as_of=now, max_age_seconds=max_age_seconds)
        except Exception:
            continue
        book = str(binding["book_key"])
        if book == candidate_book:
            continue
        if allowed is not None and book not in allowed:
            continue
        by_book.setdefault(book, []).append((quote, binding))

    fair_ps: list[float] = []
    used: list[str] = []
    cand_time = _aware(cand.get("retrieved_at"), "candidate_retrieved_at")
    for book, rows in sorted(by_book.items()):
        same = [(q, b) for q, b in rows if _outcome_key(b) == cand_key]
        if len(same) != 1:
            continue
        side_quote, _ = same[0]
        ref_time = _aware(side_quote.get("retrieved_at"), "reference_retrieved_at")
        if abs((ref_time - cand_time).total_seconds()) > max_cross_book_skew_seconds:
            continue
        try:
            opposite = _pair_for(side_quote, rows)
            probability = float(multiplicative_devig(side_quote, opposite).candidate_fair_probability)
        except Exception:
            continue
        if isfinite(probability) and 0.0 < probability < 1.0:
            fair_ps.append(probability)
            used.append(book)

    market = str(cand_binding["market_id"])
    side = str(cand_binding["side"])
    spec = MARKET_BINDINGS[market]
    line = None if spec.threshold_semantics == NO_THRESHOLD else float(cand_binding["line"])
    odds = int(cand_binding["american_odds"])
    raw_implied = 1.0 / american_to_decimal(odds)
    base = dict(
        event_id=str(cand_binding["event_id"]), market=market, side=side, line=line,
        candidate_book=candidate_book, candidate_odds=odds,
        candidate_raw_implied=raw_implied, reference_books=tuple(used),
        reference_count=len(fair_ps),
    )

    if len(fair_ps) < min_reference_books:
        return MarketDislocation(
            "BLOCKED", "REFERENCE_BOOKS_INSUFFICIENT",
            reference_fair_probability=None, probability_edge=None,
            conditional_ev_per_decision=None, exact_market_ev_per_dollar=None,
            push_mass_required_for_exact_ev=False, **base,
        )

    fair_p = float(median(fair_ps))
    decimal = american_to_decimal(odds)
    edge = fair_p - raw_implied
    conditional_ev = fair_p * decimal - 1.0
    integer_pushable = (
        spec.threshold_semantics == INTEGER_PUSHABLE
        and line is not None
        and abs(line - round(line)) < 1e-12
    )
    exact = None if integer_pushable else conditional_ev

    if edge <= 0 or conditional_ev <= 0:
        status, reason = "NO_DISLOCATION", "REFERENCE_MARKET_DOES_NOT_SUPPORT_VALUE"
    elif edge >= min_probability_edge and conditional_ev >= min_conditional_ev:
        status, reason = "MARKET_DISLOCATION", "EXECUTABLE_PRICE_BEATS_REFERENCE_MARKET"
    else:
        status, reason = "BELOW_THRESHOLD", "POSITIVE_BUT_BELOW_DISLOCATION_FLOOR"

    return MarketDislocation(
        status, reason, reference_fair_probability=fair_p, probability_edge=edge,
        conditional_ev_per_decision=conditional_ev,
        exact_market_ev_per_dollar=exact,
        push_mass_required_for_exact_ev=integer_pushable, **base,
    )
