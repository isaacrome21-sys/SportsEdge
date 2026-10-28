"""Centralized quote-freshness check for every SportsEdge pricing path.

One bound (MAX_QUOTE_AGE_SECONDS = 180), one function, explicit codes.
Every pricing path — the free game-model runner, the research bridge, the
phone prop pricers — must route quote timestamps through
``check_quote_freshness`` so a stale screenshot can never silently support a
research candidate. Research only; no betting authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

# Single bound, shared by all pricing paths. A quote older than this cannot
# support a research candidate; it becomes watch-only with an explicit code.
MAX_QUOTE_AGE_SECONDS = 180

QUOTE_FRESH = "QUOTE_FRESH_UNDER_180S"
QUOTE_STALE = "QUOTE_STALE_OVER_180S"
QUOTE_FUTURE = "QUOTE_TIMESTAMP_IN_FUTURE"
QUOTE_UNVERIFIED = "QUOTE_FRESHNESS_UNVERIFIED"
QUOTE_INVALID = "QUOTE_TIMESTAMP_INVALID"


def _parse(value: Any) -> datetime | None:
    """Parse an ISO timestamp; None when missing. Raise on malformed."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(QUOTE_INVALID) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(QUOTE_INVALID + ":TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def check_quote_freshness(captured_at: Any, *, now: datetime,
                          max_age_seconds: int = MAX_QUOTE_AGE_SECONDS) -> dict:
    """Classify one quote capture timestamp against ``now``.

    Returns {"code", "age_seconds", "max_age_seconds"}. ``age_seconds`` is None
    when the timestamp is missing or unparseable. Never raises on missing
    input; malformed input yields QUOTE_TIMESTAMP_INVALID. Caller parameters
    are validated strictly: a non-datetime ``now`` or a non-integral
    ``max_age_seconds`` (e.g. a config string) raises ValueError instead of
    crashing the comparison with a raw TypeError.
    """
    if not isinstance(now, datetime):
        raise ValueError("QUOTE_FRESHNESS_NOW_INVALID")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("QUOTE_FRESHNESS_NOW_TIMEZONE_REQUIRED")
    if isinstance(max_age_seconds, bool) \
            or not isinstance(max_age_seconds, (int, float)) \
            or (isinstance(max_age_seconds, float)
                and (not isfinite(max_age_seconds)
                     or int(max_age_seconds) != max_age_seconds)):
        raise ValueError("QUOTE_FRESHNESS_MAX_AGE_INVALID")
    max_age = int(max_age_seconds)
    now = now.astimezone(timezone.utc)
    try:
        captured = _parse(captured_at)
    except ValueError:
        return {"code": QUOTE_INVALID, "age_seconds": None,
                "max_age_seconds": max_age}
    if captured is None:
        return {"code": QUOTE_UNVERIFIED, "age_seconds": None,
                "max_age_seconds": max_age}
    age = (now - captured).total_seconds()
    if age < 0:
        return {"code": QUOTE_FUTURE, "age_seconds": round(age, 3),
                "max_age_seconds": max_age}
    if age > max_age:
        return {"code": QUOTE_STALE, "age_seconds": round(age, 3),
                "max_age_seconds": max_age}
    return {"code": QUOTE_FRESH, "age_seconds": round(age, 3),
            "max_age_seconds": max_age}


def is_fresh(result: dict) -> bool:
    """True only for a verified-fresh capture. Everything else is watch-only."""
    return isinstance(result, dict) and result.get("code") == QUOTE_FRESH
