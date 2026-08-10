#!/usr/bin/env python3
"""Reusable double-TTL sportsbook price freshness gate."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class PriceCheckResult:
    ok: bool
    reason: str
    age_seconds: Optional[float] = None


def _parse(ts: str) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    if d.tzinfo is None:
        return None
    return d.astimezone(timezone.utc)


def check_price_freshness(price: dict, now: datetime) -> PriceCheckResult:
    required = ("sportsbook", "source_surface", "game_id", "market", "line", "side",
                "odds", "retrieved_at", "ttl_seconds")
    missing = [f for f in required if f not in price]
    if missing:
        return PriceCheckResult(False, f"missing fields: {missing}")
    ttl = price["ttl_seconds"]
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
        return PriceCheckResult(False, f"missing/invalid TTL: {ttl}")
    ts = _parse(price["retrieved_at"])
    if ts is None:
        return PriceCheckResult(False, "malformed or timezone-naive retrieved_at timestamp")
    if now.tzinfo is None:
        return PriceCheckResult(False, "now must be timezone-aware")
    age = (now.astimezone(timezone.utc) - ts).total_seconds()
    if age < 0:
        return PriceCheckResult(False, "retrieved_at is in the future", age)
    if age > ttl:
        return PriceCheckResult(False, f"stale: age={age:.1f}s > ttl={ttl}s", age)
    return PriceCheckResult(True, "fresh", age)


def check_double_ttl(price: dict, ingestion_now: datetime,
                     finalization_now: datetime) -> PriceCheckResult:
    if finalization_now < ingestion_now:
        return PriceCheckResult(False, "pipeline time moved backwards")
    first = check_price_freshness(price, ingestion_now)
    if not first.ok:
        return PriceCheckResult(False, f"failed at ingestion: {first.reason}", first.age_seconds)
    second = check_price_freshness(price, finalization_now)
    if not second.ok:
        return PriceCheckResult(False, f"failed at finalization: {second.reason}", second.age_seconds)
    return PriceCheckResult(True, "fresh at both gates", second.age_seconds)
