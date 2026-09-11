"""Research-only top-down market-value lane.

This module intentionally never creates or mutates SportsEdge Model_P. It converts
two-sided sharp-book prices into ``market_fair_p`` and evaluates executable prices
against that market-derived benchmark. The frozen V1 policy keeps the lane PAPER.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from math import sqrt
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence


POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "market_value_v1.json"


def _canonical_book(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


@dataclass(frozen=True)
class MarketValuePolicy:
    policy_id: str
    lane_status: str
    devig_method: str
    min_ev: float
    american_odds_min: int
    american_odds_max: int
    reference_modes: Mapping[str, Mapping[str, object]]
    eligible_for_official: bool
    external_performance_claims_allowed: bool

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "MarketValuePolicy":
        expected = {
            "policy_id",
            "lane_status",
            "devig_method",
            "min_ev",
            "american_odds_min",
            "american_odds_max",
            "reference_modes",
            "eligible_for_official",
            "external_performance_claims_allowed",
        }
        unknown = set(raw) - expected
        missing = expected - set(raw)
        if unknown or missing:
            raise ValueError(
                f"market-value policy keys mismatch: missing={sorted(missing)} "
                f"unknown={sorted(unknown)}"
            )

        policy = cls(
            policy_id=str(raw["policy_id"]),
            lane_status=str(raw["lane_status"]),
            devig_method=str(raw["devig_method"]).upper(),
            min_ev=float(raw["min_ev"]),
            american_odds_min=int(raw["american_odds_min"]),
            american_odds_max=int(raw["american_odds_max"]),
            reference_modes=raw["reference_modes"],  # type: ignore[arg-type]
            eligible_for_official=bool(raw["eligible_for_official"]),
            external_performance_claims_allowed=bool(
                raw["external_performance_claims_allowed"]
            ),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.policy_id != "TOP_DOWN_MARKET_VALUE_V1":
            raise ValueError("unexpected market-value policy_id")
        if self.lane_status != "PAPER":
            raise ValueError("V1 market-value lane must remain PAPER")
        if self.devig_method not in {"SHIN", "PROPORTIONAL"}:
            raise ValueError("unsupported devig_method")
        if not (0.0 <= self.min_ev < 1.0):
            raise ValueError("min_ev must be in [0, 1)")
        if self.american_odds_min >= self.american_odds_max:
            raise ValueError("invalid American-odds range")
        if self.eligible_for_official:
            raise ValueError("V1 is research-only and cannot be OFFICIAL")
        if self.external_performance_claims_allowed:
            raise ValueError("external performance claims cannot validate V1")

        expected_mode_keys = {"PINNACLE_ONLY_V1", "SHARP_CONSENSUS_V1"}
        if set(self.reference_modes) != expected_mode_keys:
            raise ValueError("reference_modes must be exactly the frozen V1 modes")
        for mode_name, mode_raw in self.reference_modes.items():
            if not isinstance(mode_raw, Mapping):
                raise ValueError(f"{mode_name} must be a mapping")
            expected = {"books", "min_books", "aggregation"}
            if set(mode_raw) != expected:
                raise ValueError(f"{mode_name} keys must be exactly {sorted(expected)}")
            books = mode_raw["books"]
            if (
                not isinstance(books, Sequence)
                or isinstance(books, (str, bytes))
                or not books
            ):
                raise ValueError(f"{mode_name}.books must be a non-empty list")
            canonical_books = [_canonical_book(str(book)) for book in books]
            if len(set(canonical_books)) != len(canonical_books):
                raise ValueError(f"{mode_name}.books contains duplicates")
            min_books = int(mode_raw["min_books"])
            if min_books < 1 or min_books > len(books):
                raise ValueError(f"{mode_name}.min_books is invalid")
            aggregation = str(mode_raw["aggregation"]).lower()
            if mode_name == "PINNACLE_ONLY_V1":
                if (
                    canonical_books != ["pinnacle"]
                    or min_books != 1
                    or aggregation != "single"
                ):
                    raise ValueError("PINNACLE_ONLY_V1 contract changed")
            elif aggregation != "median":
                raise ValueError("SHARP_CONSENSUS_V1 aggregation must be median")


def load_policy(path: str | Path | None = None) -> MarketValuePolicy:
    resolved = Path(path) if path is not None else POLICY_PATH
    with resolved.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, Mapping):
        raise ValueError("market-value policy root must be an object")
    return MarketValuePolicy.from_mapping(raw)


@dataclass(frozen=True)
class PriceQuote:
    """One pregame price with exact-market provenance."""

    book: str
    market_key: str
    selection: str
    american_odds: int
    captured_at: str
    source: str

    def __post_init__(self) -> None:
        if not self.book.strip():
            raise ValueError("book is required")
        if not self.market_key.strip():
            raise ValueError("market_key is required")
        if not self.selection.strip():
            raise ValueError("selection is required")
        validate_american_odds(self.american_odds)
        _parse_timestamp(self.captured_at)
        if not self.source.strip():
            raise ValueError("source is required")


@dataclass(frozen=True)
class ReferencePair:
    """Two opposing prices from the same reference book and exact market/line."""

    first: PriceQuote
    second: PriceQuote

    def __post_init__(self) -> None:
        if _canonical_book(self.first.book) != _canonical_book(self.second.book):
            raise ValueError("reference pair must come from one book")
        if self.first.market_key != self.second.market_key:
            raise ValueError("reference pair must use the exact same market_key")
        if self.first.selection == self.second.selection:
            raise ValueError("reference pair must contain two distinct selections")

    @property
    def book(self) -> str:
        return self.first.book

    @property
    def market_key(self) -> str:
        return self.first.market_key

    def odds_for(self, selection: str) -> int:
        if self.first.selection == selection:
            return self.first.american_odds
        if self.second.selection == selection:
            return self.second.american_odds
        raise KeyError(selection)


@dataclass(frozen=True)
class MarketValueDecision:
    policy_id: str
    lane_status: str
    reference_mode: str
    devig_method: str
    market_key: str
    decision: str
    selection: str | None
    market_fair_p: float | None
    market_fair_american: int | None
    execution_book: str | None
    execution_american_odds: int | None
    execution_captured_at: str | None
    execution_source: str | None
    ev: float | None
    model_agreement: bool | None
    reason: str


@dataclass(frozen=True)
class ClosingSnapshot:
    """Post-decision close record. It cannot mutate the original decision."""

    policy_id: str
    market_key: str
    selection: str
    original_execution_book: str
    original_execution_american_odds: int
    close_market_fair_p: float
    clv: float
    reference_mode: str
    captured_at_max: str


def validate_american_odds(odds: int) -> None:
    if isinstance(odds, bool) or not isinstance(odds, int):
        raise ValueError("American odds must be an integer")
    if -100 < odds < 100:
        raise ValueError("American odds must be <= -100 or >= +100")


def american_to_decimal(odds: int) -> float:
    validate_american_odds(odds)
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


def american_to_implied_probability(odds: int) -> float:
    return 1.0 / american_to_decimal(odds)


def probability_to_american(probability: float) -> int:
    if not (0.0 < probability < 1.0):
        raise ValueError("probability must be between 0 and 1")
    if probability >= 0.5:
        value = -100.0 * probability / (1.0 - probability)
    else:
        value = 100.0 * (1.0 - probability) / probability
    return int(round(value))


def expected_value(probability: float, american_odds: int) -> float:
    if not (0.0 <= probability <= 1.0):
        raise ValueError("probability must be in [0, 1]")
    return probability * american_to_decimal(american_odds) - 1.0


def devig_proportional(odds_a: int, odds_b: int) -> tuple[float, float]:
    q_a = american_to_implied_probability(odds_a)
    q_b = american_to_implied_probability(odds_b)
    total = q_a + q_b
    if total <= 0.0:
        raise ValueError("invalid two-way market")
    return q_a / total, q_b / total


def devig_shin(odds_a: int, odds_b: int) -> tuple[float, float]:
    """Return two-way Shin fair probabilities via deterministic bisection."""

    q = [
        american_to_implied_probability(odds_a),
        american_to_implied_probability(odds_b),
    ]
    total = sum(q)
    if total < 1.0 - 1e-12:
        raise ValueError("Shin requires a non-negative reference overround")
    if abs(total - 1.0) <= 1e-12:
        return q[0], q[1]

    def probabilities(z: float) -> tuple[float, float]:
        denominator = 2.0 * (1.0 - z)
        values = [
            (sqrt(z * z + 4.0 * (1.0 - z) * (qi * qi / total)) - z)
            / denominator
            for qi in q
        ]
        return values[0], values[1]

    low = 0.0
    high = 1.0 - 1e-12
    if sum(probabilities(low)) <= 1.0 or sum(probabilities(high)) >= 1.0:
        raise ValueError("could not bracket Shin insider parameter")

    for _ in range(200):
        mid = (low + high) / 2.0
        if sum(probabilities(mid)) > 1.0:
            low = mid
        else:
            high = mid

    fair = probabilities((low + high) / 2.0)
    normalizer = sum(fair)
    return fair[0] / normalizer, fair[1] / normalizer


def _fair_pair(pair: ReferencePair, method: str) -> dict[str, float]:
    method = method.upper()
    if method == "SHIN":
        probs = devig_shin(pair.first.american_odds, pair.second.american_odds)
    elif method == "PROPORTIONAL":
        probs = devig_proportional(
            pair.first.american_odds, pair.second.american_odds
        )
    else:
        raise ValueError(f"unsupported devig method: {method}")
    return {pair.first.selection: probs[0], pair.second.selection: probs[1]}


def _mode_contract(
    policy: MarketValuePolicy, reference_mode: str
) -> tuple[list[str], int, str]:
    try:
        raw = policy.reference_modes[reference_mode]
    except KeyError as exc:
        raise ValueError(f"unsupported reference mode: {reference_mode}") from exc
    books = [_canonical_book(str(book)) for book in raw["books"]]  # type: ignore[index]
    min_books = int(raw["min_books"])  # type: ignore[index]
    aggregation = str(raw["aggregation"]).lower()  # type: ignore[index]
    return books, min_books, aggregation


def market_fair_probability(
    reference_pairs: Iterable[ReferencePair],
    *,
    selection: str,
    reference_mode: str,
    policy: MarketValuePolicy,
) -> float:
    pairs = list(reference_pairs)
    if not pairs:
        raise ValueError("at least one reference pair is required")
    market_keys = {pair.market_key for pair in pairs}
    if len(market_keys) != 1:
        raise ValueError("all reference pairs must use the exact same market_key")

    allowed_books, min_books, aggregation = _mode_contract(policy, reference_mode)
    by_book: dict[str, ReferencePair] = {}
    for pair in pairs:
        book = _canonical_book(pair.book)
        if book not in allowed_books:
            continue
        if book in by_book:
            raise ValueError(f"duplicate reference pair for book: {pair.book}")
        pair.odds_for(selection)
        by_book[book] = pair

    if len(by_book) < min_books:
        raise ValueError(
            f"{reference_mode} requires at least {min_books} eligible reference books"
        )

    if reference_mode == "PINNACLE_ONLY_V1":
        if "pinnacle" not in by_book:
            raise ValueError("PINNACLE_ONLY_V1 requires Pinnacle")
        return _fair_pair(by_book["pinnacle"], policy.devig_method)[selection]

    fair_values = [
        _fair_pair(by_book[book], policy.devig_method)[selection]
        for book in allowed_books
        if book in by_book
    ]
    if aggregation != "median":
        raise ValueError("V1 consensus aggregation must be median")
    return float(median(fair_values))


def _best_execution_quote(
    quotes: Iterable[PriceQuote],
    *,
    market_key: str,
    selection: str,
    policy: MarketValuePolicy,
) -> PriceQuote | None:
    eligible = [
        quote
        for quote in quotes
        if quote.market_key == market_key
        and quote.selection == selection
        and policy.american_odds_min <= quote.american_odds <= policy.american_odds_max
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda quote: american_to_decimal(quote.american_odds))


def evaluate_market(
    reference_pairs: Iterable[ReferencePair],
    execution_quotes: Iterable[PriceQuote],
    *,
    reference_mode: str,
    policy: MarketValuePolicy,
    independent_model_selection: str | None = None,
) -> MarketValueDecision:
    """Return the larger qualifying market-price edge as PAPER only.

    No Model_P is accepted, produced, changed, or inferred here.
    """

    pairs = list(reference_pairs)
    if not pairs:
        raise ValueError("reference_pairs is empty")
    market_keys = {pair.market_key for pair in pairs}
    if len(market_keys) != 1:
        raise ValueError("reference pairs must share one exact market_key")
    market_key = pairs[0].market_key

    selections = {pairs[0].first.selection, pairs[0].second.selection}
    for pair in pairs[1:]:
        if {pair.first.selection, pair.second.selection} != selections:
            raise ValueError("reference books disagree on market selections")

    execution_quotes = list(execution_quotes)
    candidates: list[tuple[float, str, float, PriceQuote]] = []
    for selection in sorted(selections):
        fair_p = market_fair_probability(
            pairs,
            selection=selection,
            reference_mode=reference_mode,
            policy=policy,
        )
        best = _best_execution_quote(
            execution_quotes,
            market_key=market_key,
            selection=selection,
            policy=policy,
        )
        if best is None:
            continue
        ev = expected_value(fair_p, best.american_odds)
        candidates.append((ev, selection, fair_p, best))

    if not candidates:
        return MarketValueDecision(
            policy_id=policy.policy_id,
            lane_status=policy.lane_status,
            reference_mode=reference_mode,
            devig_method=policy.devig_method,
            market_key=market_key,
            decision="NO_BET",
            selection=None,
            market_fair_p=None,
            market_fair_american=None,
            execution_book=None,
            execution_american_odds=None,
            execution_captured_at=None,
            execution_source=None,
            ev=None,
            model_agreement=None,
            reason="NO_EXECUTABLE_PRICE_IN_FROZEN_ODDS_RANGE",
        )

    ev, selection, fair_p, best = max(candidates, key=lambda item: item[0])
    agreement = (
        None
        if independent_model_selection is None
        else independent_model_selection == selection
    )
    if ev + 1e-12 < policy.min_ev:
        return MarketValueDecision(
            policy_id=policy.policy_id,
            lane_status=policy.lane_status,
            reference_mode=reference_mode,
            devig_method=policy.devig_method,
            market_key=market_key,
            decision="NO_BET",
            selection=selection,
            market_fair_p=fair_p,
            market_fair_american=probability_to_american(fair_p),
            execution_book=best.book,
            execution_american_odds=best.american_odds,
            execution_captured_at=best.captured_at,
            execution_source=best.source,
            ev=ev,
            model_agreement=agreement,
            reason="MARKET_EV_BELOW_FROZEN_THRESHOLD",
        )

    return MarketValueDecision(
        policy_id=policy.policy_id,
        lane_status=policy.lane_status,
        reference_mode=reference_mode,
        devig_method=policy.devig_method,
        market_key=market_key,
        decision="PAPER_BET",
        selection=selection,
        market_fair_p=fair_p,
        market_fair_american=probability_to_american(fair_p),
        execution_book=best.book,
        execution_american_odds=best.american_odds,
        execution_captured_at=best.captured_at,
        execution_source=best.source,
        ev=ev,
        model_agreement=agreement,
        reason="MARKET_EV_CLEARS_FROZEN_THRESHOLD_RESEARCH_ONLY",
    )


def record_close(
    decision: MarketValueDecision,
    closing_reference_pairs: Iterable[ReferencePair],
    *,
    policy: MarketValuePolicy,
) -> ClosingSnapshot:
    if decision.decision != "PAPER_BET":
        raise ValueError("only a PAPER_BET can receive a closing snapshot")
    if (
        decision.selection is None
        or decision.execution_book is None
        or decision.execution_american_odds is None
    ):
        raise ValueError("decision is missing execution fields")

    pairs = list(closing_reference_pairs)
    if not pairs:
        raise ValueError("closing reference pairs are required")
    if any(pair.market_key != decision.market_key for pair in pairs):
        raise ValueError("closing market_key must match original decision")

    close_p = market_fair_probability(
        pairs,
        selection=decision.selection,
        reference_mode=decision.reference_mode,
        policy=policy,
    )
    timestamps = [
        quote.captured_at
        for pair in pairs
        for quote in (pair.first, pair.second)
    ]
    return ClosingSnapshot(
        policy_id=decision.policy_id,
        market_key=decision.market_key,
        selection=decision.selection,
        original_execution_book=decision.execution_book,
        original_execution_american_odds=decision.execution_american_odds,
        close_market_fair_p=close_p,
        clv=expected_value(close_p, decision.execution_american_odds),
        reference_mode=decision.reference_mode,
        captured_at_max=max(timestamps, key=_parse_timestamp),
    )
