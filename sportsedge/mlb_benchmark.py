"""Deterministic no-vig MLB benchmark and exact-original-contract CLV.

Market-provider hierarchy is downstream of Model_P. This module never chooses the
provider that makes SportsEdge look best: it uses the first frozen provider tier with a
fresh synchronized exact-contract pair. CLV is unavailable if the original contract
cannot be priced at close; no unvalidated line repricing is performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from sportsedge.core.probability_contract import american_to_decimal


class MLBBenchmarkError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise MLBBenchmarkError(f"{field}:TIMESTAMP_REQUIRED")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MLBBenchmarkError(f"{field}:TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBBenchmarkError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _line(value: Any) -> float:
    out = float(value)
    if not isfinite(out):
        raise MLBBenchmarkError("LINE_NONFINITE")
    return out


def _same_line(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= 1e-12


def _raw_probability(odds: float) -> float:
    return 1.0 / american_to_decimal(float(odds))


def _expected_sides(market: str) -> tuple[frozenset[str], ...]:
    name = str(market).upper()
    if name in {"MONEYLINE", "F5_MONEYLINE"}:
        return (frozenset({"HOME", "AWAY"}), frozenset({"HOME_ML", "AWAY_ML"}))
    if name in {"RUN_LINE", "F5_RUN_LINE"}:
        return (frozenset({"HOME", "AWAY"}), frozenset({"HOME_RL", "AWAY_RL"}))
    if name in {"TOTALS", "F5_TOTALS", "TEAM_TOTALS", "F5_TEAM_TOTALS"} or name.startswith("PITCHER_") or name.startswith("HITTER_"):
        return (frozenset({"OVER", "UNDER"}),)
    if name in {"NRFI", "YRFI", "PITCHER_RECORD_WIN", "FIRST_HOME_RUN"}:
        return (frozenset({"YES", "NO"}),)
    return (frozenset({"OVER", "UNDER"}), frozenset({"YES", "NO"}), frozenset({"HOME", "AWAY"}))


@dataclass(frozen=True)
class MLBBenchmarkQuote:
    quote_id: str
    provider: str
    book: str
    game_id: str
    market: str
    entity_id: str
    period: str
    side: str
    line: float
    american_odds: float
    captured_at: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "MLBBenchmarkQuote":
        return cls(
            quote_id=str(row.get("quote_id") or row.get("offer_id") or ""),
            provider=str(row.get("provider") or row.get("book_key") or "").upper(),
            book=str(row.get("book") or row.get("book_key") or "").upper(),
            game_id=str(row.get("game_id") or ""),
            market=str(row.get("market") or "").upper(),
            entity_id=str(row.get("entity_id") or ""),
            period=str(row.get("period") or "FG").upper(),
            side=str(row.get("side") or "").upper(),
            line=_line(row.get("line", 0.0)),
            american_odds=float(row.get("american_odds")),
            captured_at=_utc(row.get("captured_at", row.get("retrieved_at")), "captured_at").isoformat(),
        ).validate()

    def validate(self) -> "MLBBenchmarkQuote":
        if not all((self.quote_id, self.provider, self.book, self.game_id, self.market, self.entity_id, self.period, self.side)):
            raise MLBBenchmarkError("QUOTE_IDENTITY_REQUIRED")
        _line(self.line)
        _raw_probability(self.american_odds)
        _utc(self.captured_at, "captured_at")
        return self


@dataclass(frozen=True)
class MLBBenchmarkPair:
    game_id: str
    market: str
    entity_id: str
    period: str
    line: float
    provider: str
    book: str
    quote_ids: tuple[str, str]
    sides: tuple[str, str]
    novig_probabilities: tuple[float, float]
    reference_ts: str
    pair_skew_seconds: float
    tier_index: int
    fallback_used: bool

    def probability(self, side: str) -> float:
        wanted = str(side).upper()
        for current, p in zip(self.sides, self.novig_probabilities):
            if current == wanted:
                return float(p)
        raise MLBBenchmarkError(f"REFERENCE_SIDE_MISSING:{side}")


def _pair_identity(q: MLBBenchmarkQuote) -> tuple[str, str, str, str, str, float]:
    return (q.game_id, q.market, q.entity_id, q.period, q.book, q.line)


def _candidate_pairs(quotes: Iterable[MLBBenchmarkQuote]) -> list[tuple[MLBBenchmarkQuote, MLBBenchmarkQuote]]:
    grouped: dict[tuple[str, str, str, str, str, float], list[MLBBenchmarkQuote]] = {}
    for quote in quotes:
        q = quote.validate()
        grouped.setdefault(_pair_identity(q), []).append(q)
    out = []
    for key, rows in grouped.items():
        if len(rows) != 2:
            continue
        if rows[0].provider != rows[1].provider:
            continue
        side_set = frozenset(row.side for row in rows)
        if side_set not in _expected_sides(key[1]):
            continue
        out.append((rows[0], rows[1]))
    return out


def select_mlb_reference_pair(
    quotes: Iterable[MLBBenchmarkQuote | Mapping[str, Any]],
    *,
    game_id: str,
    market: str,
    entity_id: str,
    period: str,
    line: float,
    cutoff_ts: datetime | str,
    provider_priority_tiers: Sequence[Sequence[str]],
    max_quote_age_seconds: int = 180,
    max_pair_skew_seconds: int = 30,
) -> MLBBenchmarkPair:
    cutoff = _utc(cutoff_ts, "cutoff_ts")
    if isinstance(max_quote_age_seconds, bool) or int(max_quote_age_seconds) < 0:
        raise MLBBenchmarkError("MAX_QUOTE_AGE_INVALID")
    if isinstance(max_pair_skew_seconds, bool) or int(max_pair_skew_seconds) < 0:
        raise MLBBenchmarkError("MAX_PAIR_SKEW_INVALID")
    normalized = [q if isinstance(q, MLBBenchmarkQuote) else MLBBenchmarkQuote.from_mapping(q) for q in quotes]
    valid = []
    for left, right in _candidate_pairs(normalized):
        if left.game_id != str(game_id) or left.market != str(market).upper() or left.entity_id != str(entity_id) or left.period != str(period).upper() or not _same_line(left.line, float(line)):
            continue
        lt, rt = _utc(left.captured_at, "captured_at"), _utc(right.captured_at, "captured_at")
        latest, earliest = max(lt, rt), min(lt, rt)
        if latest > cutoff:
            continue
        if (cutoff - earliest).total_seconds() > int(max_quote_age_seconds):
            continue
        if (latest - earliest).total_seconds() > int(max_pair_skew_seconds):
            continue
        valid.append((left, right))
    for tier_index, tier in enumerate(provider_priority_tiers):
        allowed = {str(x).upper() for x in tier}
        rows = [pair for pair in valid if pair[0].provider in allowed]
        if not rows:
            continue
        rows.sort(key=lambda pair: (max(_utc(pair[0].captured_at, "captured_at"), _utc(pair[1].captured_at, "captured_at")), pair[0].provider, pair[0].book), reverse=True)
        left, right = rows[0]
        p1, p2 = _raw_probability(left.american_odds), _raw_probability(right.american_odds)
        total = p1 + p2
        if not isfinite(total) or total <= 0.0:
            raise MLBBenchmarkError("DEVIG_SUM_INVALID")
        lt, rt = _utc(left.captured_at, "captured_at"), _utc(right.captured_at, "captured_at")
        return MLBBenchmarkPair(
            game_id=left.game_id,
            market=left.market,
            entity_id=left.entity_id,
            period=left.period,
            line=left.line,
            provider=left.provider,
            book=left.book,
            quote_ids=(left.quote_id, right.quote_id),
            sides=(left.side, right.side),
            novig_probabilities=(p1 / total, p2 / total),
            reference_ts=max(lt, rt).isoformat(),
            pair_skew_seconds=abs((lt - rt).total_seconds()),
            tier_index=tier_index,
            fallback_used=tier_index > 0,
        )
    raise MLBBenchmarkError("REFERENCE_PAIR_UNAVAILABLE")


@dataclass(frozen=True)
class MLBOriginalContractCLV:
    side: str
    decision_novig_probability: float
    closing_novig_probability: float
    clv_probability_points: float
    model_vs_close_probability_points: float | None


def score_mlb_original_contract_clv(
    *,
    side: str,
    decision_reference: MLBBenchmarkPair,
    closing_reference: MLBBenchmarkPair,
    model_p_at_decision: float | None = None,
) -> MLBOriginalContractCLV:
    identity_decision = (decision_reference.game_id, decision_reference.market, decision_reference.entity_id, decision_reference.period)
    identity_close = (closing_reference.game_id, closing_reference.market, closing_reference.entity_id, closing_reference.period)
    if identity_decision != identity_close:
        raise MLBBenchmarkError("CLV_CONTRACT_IDENTITY_MISMATCH")
    if not _same_line(decision_reference.line, closing_reference.line):
        raise MLBBenchmarkError("CLV_ORIGINAL_CONTRACT_LINE_MISMATCH")
    decision_p = decision_reference.probability(side)
    close_p = closing_reference.probability(side)
    residual = None
    if model_p_at_decision is not None:
        model = float(model_p_at_decision)
        if not isfinite(model) or not 0.0 <= model <= 1.0:
            raise MLBBenchmarkError("MODEL_P_RANGE")
        residual = model - close_p
    return MLBOriginalContractCLV(
        side=str(side).upper(),
        decision_novig_probability=decision_p,
        closing_novig_probability=close_p,
        clv_probability_points=close_p - decision_p,
        model_vs_close_probability_points=residual,
    )
