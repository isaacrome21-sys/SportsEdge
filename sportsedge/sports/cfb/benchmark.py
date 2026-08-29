"""Deterministic CFB market benchmark and original-contract CLV helpers.

Market data in this module is downstream-only. Nothing here may be imported by the
predictive feature builder to create Model_P.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence


class CFBBenchmarkError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBBenchmarkError(f"{field}:TIMESTAMP_REQUIRED")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBBenchmarkError(f"{field}:ISO8601_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBBenchmarkError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def american_to_raw_probability(odds: float) -> float:
    value = float(odds)
    if not isfinite(value) or (-100.0 < value < 100.0):
        raise CFBBenchmarkError("AMERICAN_ODDS_INVALID")
    return (-value) / ((-value) + 100.0) if value < 0 else 100.0 / (value + 100.0)


def devig_pair(odds_a: float, odds_b: float) -> tuple[float, float]:
    a = american_to_raw_probability(odds_a)
    b = american_to_raw_probability(odds_b)
    denominator = a + b
    if denominator <= 0.0:
        raise CFBBenchmarkError("DEVIG_DENOMINATOR_INVALID")
    return a / denominator, b / denominator


def _same_line(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) <= 1e-9


@dataclass(frozen=True)
class BenchmarkQuote:
    quote_id: str
    provider: str
    book: str
    game_id: str
    market: str
    side: str
    line: float | None
    american_odds: float
    captured_at: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "BenchmarkQuote":
        line = row.get("line")
        return cls(
            quote_id=str(row.get("quote_id") or row.get("offer_id") or "").strip(),
            provider=str(row.get("provider") or row.get("book_key") or row.get("book") or "").strip().upper(),
            book=str(row.get("book") or row.get("sportsbook") or row.get("book_key") or "").strip().upper(),
            game_id=str(row.get("game_id") or "").strip(),
            market=str(row.get("market") or "").strip().upper(),
            side=str(row.get("side") or "").strip().upper(),
            line=None if line is None else float(line),
            american_odds=float(row.get("american_odds")),
            captured_at=str(row.get("captured_at") or row.get("retrieved_at") or "").strip(),
        ).validate()

    def validate(self) -> "BenchmarkQuote":
        if not self.quote_id or not self.provider or not self.book or not self.game_id:
            raise CFBBenchmarkError("QUOTE_IDENTITY_REQUIRED")
        if self.market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            raise CFBBenchmarkError("QUOTE_MARKET_UNSUPPORTED")
        allowed = {"HOME", "AWAY"} if self.market in {"MONEYLINE", "SPREAD"} else {"OVER", "UNDER"}
        if self.side not in allowed:
            raise CFBBenchmarkError("QUOTE_SIDE_INVALID")
        if self.market == "MONEYLINE" and self.line not in {None, 0.0}:
            raise CFBBenchmarkError("MONEYLINE_LINE_INVALID")
        if self.market != "MONEYLINE" and self.line is None:
            raise CFBBenchmarkError("LINE_MARKET_LINE_REQUIRED")
        american_to_raw_probability(self.american_odds)
        _utc(self.captured_at, "captured_at")
        return self


@dataclass(frozen=True)
class BenchmarkPair:
    game_id: str
    market: str
    line: float | None
    provider: str
    book: str
    quote_ids: tuple[str, str]
    sides: tuple[str, str]
    novig_probabilities: tuple[float, float]
    reference_ts: str
    tier_index: int
    fallback_used: bool

    def probability(self, side: str) -> float:
        key = str(side).upper()
        for current, probability in zip(self.sides, self.novig_probabilities):
            if current == key:
                return float(probability)
        raise CFBBenchmarkError(f"REFERENCE_SIDE_MISSING:{side}")


def _complementary(market: str, sides: set[str]) -> bool:
    expected = {"HOME", "AWAY"} if market in {"MONEYLINE", "SPREAD"} else {"OVER", "UNDER"}
    return sides == expected


def _pairs(quotes: Iterable[BenchmarkQuote]) -> list[tuple[BenchmarkQuote, BenchmarkQuote]]:
    grouped: dict[tuple[str, str, str, float | None], list[BenchmarkQuote]] = {}
    for quote in quotes:
        q = quote.validate()
        grouped.setdefault((q.game_id, q.market, q.book, q.line), []).append(q)
    out: list[tuple[BenchmarkQuote, BenchmarkQuote]] = []
    for key, rows in grouped.items():
        if len(rows) != 2 or not _complementary(key[1], {r.side for r in rows}):
            continue
        if rows[0].provider != rows[1].provider:
            raise CFBBenchmarkError("REFERENCE_PAIR_PROVIDER_MISMATCH")
        out.append((rows[0], rows[1]))
    return out


def select_reference_pair(
    quotes: Iterable[BenchmarkQuote | Mapping[str, Any]],
    *,
    game_id: str,
    market: str,
    line: float | None,
    cutoff_ts: datetime | str,
    provider_priority_tiers: Sequence[Sequence[str]],
    max_quote_age_seconds: int,
) -> BenchmarkPair:
    """Select a deterministic two-sided reference with no post-hoc best-price shopping.

    The first priority tier with a valid exact-contract pair wins. Within the tier the
    freshest pair wins; deterministic provider/book ordering breaks exact timestamp ties.
    """

    cutoff = _utc(cutoff_ts, "cutoff_ts")
    if isinstance(max_quote_age_seconds, bool) or int(max_quote_age_seconds) < 0:
        raise CFBBenchmarkError("MAX_QUOTE_AGE_INVALID")
    normalized = [q if isinstance(q, BenchmarkQuote) else BenchmarkQuote.from_mapping(q) for q in quotes]
    candidates: list[tuple[BenchmarkQuote, BenchmarkQuote]] = []
    for left, right in _pairs(normalized):
        if left.game_id != str(game_id) or left.market != str(market).upper():
            continue
        if not _same_line(left.line, line):
            continue
        latest = max(_utc(left.captured_at, "captured_at"), _utc(right.captured_at, "captured_at"))
        earliest = min(_utc(left.captured_at, "captured_at"), _utc(right.captured_at, "captured_at"))
        if latest > cutoff:
            continue
        if (cutoff - earliest).total_seconds() > int(max_quote_age_seconds):
            continue
        candidates.append((left, right))
    for tier_index, tier in enumerate(provider_priority_tiers):
        allowed = {str(x).strip().upper() for x in tier}
        tier_rows = [pair for pair in candidates if pair[0].provider in allowed]
        if not tier_rows:
            continue
        tier_rows.sort(
            key=lambda pair: (
                max(_utc(pair[0].captured_at, "captured_at"), _utc(pair[1].captured_at, "captured_at")),
                pair[0].provider,
                pair[0].book,
            ),
            reverse=True,
        )
        left, right = tier_rows[0]
        probs = devig_pair(left.american_odds, right.american_odds)
        reference_ts = max(_utc(left.captured_at, "captured_at"), _utc(right.captured_at, "captured_at")).isoformat()
        return BenchmarkPair(
            game_id=left.game_id,
            market=left.market,
            line=left.line,
            provider=left.provider,
            book=left.book,
            quote_ids=(left.quote_id, right.quote_id),
            sides=(left.side, right.side),
            novig_probabilities=(probs[0], probs[1]),
            reference_ts=reference_ts,
            tier_index=tier_index,
            fallback_used=tier_index > 0,
        )
    raise CFBBenchmarkError("REFERENCE_PAIR_UNAVAILABLE")


@dataclass(frozen=True)
class OriginalContractCLV:
    side: str
    decision_novig_probability: float
    closing_novig_probability: float
    clv_probability_points: float
    model_vs_close_probability_points: float | None


def score_original_contract_clv(
    *,
    side: str,
    decision_reference: BenchmarkPair,
    closing_reference: BenchmarkPair,
    model_p_at_decision: float | None = None,
) -> OriginalContractCLV:
    """Score CLV only when both references price the exact original contract."""

    if decision_reference.game_id != closing_reference.game_id or decision_reference.market != closing_reference.market:
        raise CFBBenchmarkError("CLV_CONTRACT_IDENTITY_MISMATCH")
    if not _same_line(decision_reference.line, closing_reference.line):
        raise CFBBenchmarkError("CLV_ORIGINAL_CONTRACT_LINE_MISMATCH")
    decision_p = decision_reference.probability(side)
    close_p = closing_reference.probability(side)
    residual: float | None = None
    if model_p_at_decision is not None:
        model = float(model_p_at_decision)
        if not isfinite(model) or not 0.0 <= model <= 1.0:
            raise CFBBenchmarkError("MODEL_P_RANGE")
        residual = model - close_p
    return OriginalContractCLV(
        side=str(side).upper(),
        decision_novig_probability=decision_p,
        closing_novig_probability=close_p,
        clv_probability_points=close_p - decision_p,
        model_vs_close_probability_points=residual,
    )
