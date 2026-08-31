from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

from .truth_gate import american_to_decimal


class DevigError(ValueError):
    pass


@dataclass(frozen=True)
class DevigResult:
    method: str
    candidate_raw_implied: float
    opposite_raw_implied: float
    overround: float
    candidate_fair_probability: float
    opposite_fair_probability: float


def _raw_implied(odds: Any) -> float:
    return 1.0 / american_to_decimal(odds)


def _strict_bool(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise DevigError(f"{field} must be bool")
    return value


def _identity(quote: Mapping[str, Any]) -> tuple[str, str, str, str, str, bool]:
    try:
        alternate = _strict_bool(quote.get("is_alternate", False), field="is_alternate")
        return (
            str(quote["game_id"]),
            str(quote.get("period", "FG")),
            str(quote["market"]),
            str(quote["entity_id"]),
            str(quote.get("book_key", "")),
            alternate,
        )
    except DevigError:
        raise
    except Exception as exc:
        raise DevigError("paired quote identity incomplete") from exc


def _line_key(quote: Mapping[str, Any]) -> float:
    try:
        line = float(quote["line"])
    except Exception as exc:
        raise DevigError("paired quote line invalid") from exc
    if not isfinite(line):
        raise DevigError("paired quote line must be finite")
    market = str(quote.get("market", ""))
    if market in {"RUN_LINE", "F5_RUN_LINE"}:
        return abs(line)
    return line


def _complementary_sides(a: str, b: str) -> bool:
    pair = {a.upper(), b.upper()}
    return pair in (
        {"OVER", "UNDER"}, {"HOME", "AWAY"}, {"HOME_ML", "AWAY_ML"},
        {"HOME_RL", "AWAY_RL"}, {"YES", "NO"},
    )


def _aware_utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise DevigError(f"{field} required")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise DevigError(f"{field} invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DevigError(f"{field} timezone required")
    return dt.astimezone(timezone.utc)


def validate_pair(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> None:
    if _identity(candidate) != _identity(opposite):
        raise DevigError("paired quote identity mismatch")
    if _line_key(candidate) != _line_key(opposite):
        raise DevigError("paired quote line mismatch")
    if not _complementary_sides(str(candidate.get("side", "")), str(opposite.get("side", ""))):
        raise DevigError("paired quote sides are not complementary")


def validate_pair_temporal(
    candidate: Mapping[str, Any],
    opposite: Mapping[str, Any],
    *,
    cutoff: datetime | str,
    max_age_seconds: int = 180,
    max_skew_seconds: int = 30,
) -> None:
    """Require an exact pair to represent one synchronized market state."""

    validate_pair(candidate, opposite)
    if isinstance(max_age_seconds, bool) or int(max_age_seconds) < 0:
        raise DevigError("paired quote max age invalid")
    if isinstance(max_skew_seconds, bool) or int(max_skew_seconds) < 0:
        raise DevigError("paired quote max skew invalid")
    now = _aware_utc(cutoff, "pair cutoff")
    left = _aware_utc(candidate.get("retrieved_at"), "candidate retrieved_at")
    right = _aware_utc(opposite.get("retrieved_at"), "opposite retrieved_at")
    if left > now or right > now:
        raise DevigError("PAIRED_QUOTE_FROM_FUTURE")
    if (now - left).total_seconds() > int(max_age_seconds) or (now - right).total_seconds() > int(max_age_seconds):
        raise DevigError("PAIRED_QUOTE_STALE")
    if abs((left - right).total_seconds()) > int(max_skew_seconds):
        raise DevigError("PAIRED_QUOTE_TIMESTAMP_SKEW")


def find_paired_quote(candidate: Mapping[str, Any], quotes: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    matches: list[Mapping[str, Any]] = []
    for quote in quotes:
        if quote is candidate or dict(quote) == dict(candidate):
            continue
        try:
            validate_pair(candidate, quote)
        except DevigError:
            continue
        matches.append(quote)
    if len(matches) != 1:
        raise DevigError(f"PAIRED_PRICE_REQUIRED_FOR_DEVIG: found={len(matches)}")
    return matches[0]


def multiplicative_devig(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> DevigResult:
    """Remove two-sided margin by normalizing raw implied probabilities to sum to one."""
    validate_pair(candidate, opposite)
    q1 = _raw_implied(candidate.get("american_odds"))
    q2 = _raw_implied(opposite.get("american_odds"))
    total = q1 + q2
    if not isfinite(total) or total <= 0:
        raise DevigError("invalid paired implied-probability sum")
    p1 = q1 / total
    p2 = q2 / total
    return DevigResult(
        method="MULTIPLICATIVE_V1",
        candidate_raw_implied=q1,
        opposite_raw_implied=q2,
        overround=total - 1.0,
        candidate_fair_probability=p1,
        opposite_fair_probability=p2,
    )
