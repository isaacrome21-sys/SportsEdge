from datetime import datetime, timezone
import math
from typing import Any, Mapping


class PriceFreshnessError(ValueError):
    pass


def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PriceFreshnessError(f"{name} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)


def validate_price_freshness(quote: Mapping[str, Any], now: datetime) -> float:
    if "ttl_seconds" not in quote or "retrieved_at" not in quote:
        raise PriceFreshnessError("price requires retrieved_at and ttl_seconds")
    try:
        ttl = float(quote["ttl_seconds"])
    except (TypeError, ValueError):
        raise PriceFreshnessError("ttl_seconds must be numeric")
    if not math.isfinite(ttl) or ttl <= 0:
        raise PriceFreshnessError("ttl_seconds must be finite and > 0")
    retrieved = _aware(quote["retrieved_at"], "retrieved_at")
    current = _aware(now, "now")
    age = (current - retrieved).total_seconds()
    if age < 0:
        raise PriceFreshnessError("retrieved_at is in the future / pipeline time moved backwards")
    if age > ttl:
        raise PriceFreshnessError("price is stale")
    return age


def double_ttl_gate(quote: Mapping[str, Any], ingestion_now: datetime, finalization_now: datetime) -> tuple[float, float]:
    ingest_age = validate_price_freshness(quote, ingestion_now)
    if _aware(finalization_now, "finalization_now") < _aware(ingestion_now, "ingestion_now"):
        raise PriceFreshnessError("finalization precedes ingestion")
    final_age = validate_price_freshness(quote, finalization_now)
    return ingest_age, final_age
