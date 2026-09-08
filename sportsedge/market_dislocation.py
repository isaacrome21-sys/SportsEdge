"""Market-only stale-price / value scanner.

This module never creates Model_P. It compares an executable quote with a
same-instant, same-contract, de-vigged reference market. Reference prices are
MARKET data and are prohibited from entering predictive model features.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import median
from typing import Any, Iterable, Mapping

from .devig import multiplicative_devig
from .mlb_market_binding_v13 import (
    INTEGER_PUSHABLE,
    MARKET_BINDINGS,
    NO_THRESHOLD,
    N_WAY,
    runtime_quote_binding_row,
    validate_quote_binding,
    validate_quote_pair,
)
from .truth_gate import american_to_decimal


class MarketDislocationError(ValueError):
    pass


PROHIBITED_MODEL_KEYS = frozenset({
    "model_p", "model_probability", "sportsedge_probability", "model_edge",
    "model_ev", "fair_model_probability", "model_input", "model_output",
})
# These canonical IDs still have unresolved settlement/market-shape semantics for
# this scanner. They remain visible but fail closed rather than being priced with
# a convenient two-way assumption.
DISLOCATION_BLOCKED_MARKETS = frozenset({"F5_MONEYLINE", "FIRST_HOME_RUN"})


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
    reference_probability_spread: float | None
    probability_edge: float | None
    conditional_ev_per_decision: float | None
    exact_market_ev_per_dollar: float | None
    push_mass_required_for_exact_ev: bool


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MarketDislocationError(f"{field}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key).lower()
            yield from _walk_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_keys(item)


def _reject_model_contamination(row: Mapping[str, Any]) -> None:
    bad = PROHIBITED_MODEL_KEYS.intersection(_walk_keys(row))
    if bad:
        raise MarketDislocationError(f"MODEL_DATA_PROHIBITED_IN_MARKET_SCANNER:{sorted(bad)}")


def _validated(row: Mapping[str, Any], *, as_of: datetime, max_age_seconds: float) -> dict[str, Any]:
    _reject_model_contamination(row)
    q = dict(row)
    bind = runtime_quote_binding_row(q)
    validate_quote_binding(bind)
    retrieved = _aware(q["retrieved_at"], "retrieved_at")
    if retrieved > as_of:
        raise MarketDislocationError("QUOTE_FROM_FUTURE")
    age = (as_of - retrieved).total_seconds()
    if age > max_age_seconds:
        raise MarketDislocationError(f"QUOTE_STALE:{age:.1f}>{max_age_seconds}")
    return q


def _outcome_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    b = runtime_quote_binding_row(row)
    market = b["market_id"]
    spec = MARKET_BINDINGS[market]
    subject = (
        str(b.get("team_id")) if "team_id" in b else
        str(b.get("entity_id")) if "entity_id" in b else
        tuple(map(str, b.get("entity_ids") or ())) if "entity_ids" in b else
        "GAME"
    )
    line = None if spec.threshold_semantics == NO_THRESHOLD else float(b["line"])
    return (
        str(b["event_id"]), int(b["game_number"]), str(b["period"]), market,
        str(b["side"]), subject, line, bool(b["is_alternate"]),
    )


def _pair_for(side_quote: Mapping[str, Any], book_quotes: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    matches: list[Mapping[str, Any]] = []
    side_binding = runtime_quote_binding_row(side_quote)
    for other in book_quotes:
        if other is side_quote or dict(other) == dict(side_quote):
            continue
        try:
            validate_quote_pair(side_binding, runtime_quote_binding_row(other))
        except Exception:
            continue
        matches.append(other)
    if len(matches) != 1:
        raise MarketDislocationError(f"REFERENCE_PAIR_AMBIGUOUS_OR_MISSING:{len(matches)}")
    return matches[0]


def scan_market_dislocation(
    candidate: Mapping[str, Any],
    quote_snapshot: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
    reference_books: Iterable[str] | None = None,
    min_reference_books: int = 2,
    max_age_seconds: float = 120.0,
    max_cross_book_skew_seconds: float = 60.0,
    max_reference_probability_spread: float = 0.04,
    min_probability_edge: float = 0.01,
    min_conditional_ev: float = 0.01,
) -> MarketDislocation:
    """Compare one executable price with de-vigged reference books.

    `conditional_ev_per_decision` is exact when the wager cannot push. For an
    integer pushable line it is the EV conditional on the wager being decided;
    exact per-dollar EV needs independent push mass and is not fabricated here.

    Reference books are kept separate first. If their no-vig fair probabilities
    materially conflict, the scan BLOCKS instead of silently averaging them.
    """
    now = _aware(as_of, "as_of")
    if min_reference_books < 1:
        raise MarketDislocationError("MIN_REFERENCE_BOOKS_INVALID")
    numeric_guards = (
        min_probability_edge,
        min_conditional_ev,
        max_reference_probability_spread,
        max_age_seconds,
        max_cross_book_skew_seconds,
    )
    if any(not isfinite(float(x)) for x in numeric_guards):
        raise MarketDislocationError("SCANNER_THRESHOLD_INVALID")
    if max_reference_probability_spread < 0 or max_age_seconds <= 0 or max_cross_book_skew_seconds < 0:
        raise MarketDislocationError("SCANNER_THRESHOLD_INVALID")

    cand = _validated(candidate, as_of=now, max_age_seconds=max_age_seconds)
    market = str(cand["market"])
    side = str(cand["side"])
    spec = MARKET_BINDINGS[market]
    line = None if spec.threshold_semantics == NO_THRESHOLD else float(cand["line"])
    odds = int(cand["american_odds"])
    raw_implied = 1.0 / american_to_decimal(odds)
    candidate_book = str(cand["book_key"])

    empty_base = dict(
        event_id=str(cand["event_id"]), market=market, side=side, line=line,
        candidate_book=candidate_book, candidate_odds=odds,
        candidate_raw_implied=raw_implied, reference_books=(), reference_count=0,
        reference_probability_spread=None,
    )
    if market in DISLOCATION_BLOCKED_MARKETS or spec.ways == N_WAY:
        return MarketDislocation(
            "BLOCKED", "MARKET_SEMANTICS_NOT_APPROVED_FOR_DISLOCATION",
            reference_fair_probability=None, probability_edge=None,
            conditional_ev_per_decision=None, exact_market_ev_per_dollar=None,
            push_mass_required_for_exact_ev=False, **empty_base,
        )

    cand_key = _outcome_key(cand)
    allowed_books = None if reference_books is None else {str(x) for x in reference_books if str(x)}

    pool: list[dict[str, Any]] = []
    for raw in quote_snapshot:
        try:
            q = _validated(raw, as_of=now, max_age_seconds=max_age_seconds)
        except Exception:
            continue
        if str(q["book_key"]) == candidate_book:
            continue
        if allowed_books is not None and str(q["book_key"]) not in allowed_books:
            continue
        pool.append(q)

    by_book: dict[str, list[dict[str, Any]]] = {}
    for q in pool:
        by_book.setdefault(str(q["book_key"]), []).append(q)

    fair_ps: list[float] = []
    used_books: list[str] = []
    cand_time = _aware(cand["retrieved_at"], "candidate_retrieved_at")
    for book, rows in sorted(by_book.items()):
        same_side = [q for q in rows if _outcome_key(q) == cand_key]
        if len(same_side) != 1:
            continue
        side_quote = same_side[0]
        ref_time = _aware(side_quote["retrieved_at"], "reference_retrieved_at")
        if abs((ref_time - cand_time).total_seconds()) > max_cross_book_skew_seconds:
            continue
        try:
            opposite = _pair_for(side_quote, rows)
            result = multiplicative_devig(side_quote, opposite)
        except Exception:
            continue
        p = float(result.candidate_fair_probability)
        if not isfinite(p) or not 0 < p < 1:
            continue
        fair_ps.append(p)
        used_books.append(book)

    spread = (max(fair_ps) - min(fair_ps)) if len(fair_ps) >= 2 else None
    base = dict(
        event_id=str(cand["event_id"]), market=market, side=side, line=line,
        candidate_book=candidate_book, candidate_odds=odds,
        candidate_raw_implied=raw_implied, reference_books=tuple(used_books),
        reference_count=len(fair_ps), reference_probability_spread=spread,
    )
    if len(fair_ps) < min_reference_books:
        return MarketDislocation(
            "BLOCKED", "REFERENCE_BOOKS_INSUFFICIENT", reference_fair_probability=None,
            probability_edge=None, conditional_ev_per_decision=None,
            exact_market_ev_per_dollar=None, push_mass_required_for_exact_ev=False,
            **base,
        )
    if spread is not None and spread > max_reference_probability_spread:
        return MarketDislocation(
            "BLOCKED", "REFERENCE_MARKET_CONFLICT", reference_fair_probability=None,
            probability_edge=None, conditional_ev_per_decision=None,
            exact_market_ev_per_dollar=None, push_mass_required_for_exact_ev=False,
            **base,
        )

    fair_p = float(median(fair_ps))
    decimal = american_to_decimal(odds)
    probability_edge = fair_p - raw_implied
    conditional_ev = fair_p * decimal - 1.0
    integer_pushable = (
        spec.threshold_semantics == INTEGER_PUSHABLE and line is not None
        and abs(line - round(line)) < 1e-12
    )
    exact_ev = None if integer_pushable else conditional_ev

    if probability_edge <= 0 or conditional_ev <= 0:
        status, reason = "NO_DISLOCATION", "REFERENCE_MARKET_DOES_NOT_SUPPORT_VALUE"
    elif probability_edge >= min_probability_edge and conditional_ev >= min_conditional_ev:
        status, reason = "MARKET_DISLOCATION", "EXECUTABLE_PRICE_BEATS_REFERENCE_MARKET"
    else:
        status, reason = "BELOW_THRESHOLD", "POSITIVE_BUT_BELOW_DISLOCATION_FLOOR"

    return MarketDislocation(
        status, reason, reference_fair_probability=fair_p,
        probability_edge=probability_edge,
        conditional_ev_per_decision=conditional_ev,
        exact_market_ev_per_dollar=exact_ev,
        push_mass_required_for_exact_ev=integer_pushable,
        **base,
    )
