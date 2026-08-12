"""Normalize timestamped sportsbook offers into canonical SportsEdge quotes."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from .runtime import parse_timestamp, RuntimeInputError


class QuoteBridgeError(ValueError):
    pass


SUPPORTED_MARKETS = {"HITS", "TOTAL_BASES", "PITCHER_BB", "MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI"}
SUPPORTED_SIDES = {"OVER", "UNDER", "HOME", "AWAY"}
# Current production engines model full-game outcomes only, EXCEPT NRFI/YRFI
# which are inherently first-inning markets by definition -- their period is
# always 1ST, never FG. Keep period support market-specific so future F5/1ST
# engines for OTHER markets must earn an explicit contract rather than
# silently reusing full-game Model_P.
SUPPORTED_PERIODS_BY_MARKET = {
    "HITS": {"FG"},
    "TOTAL_BASES": {"FG"},
    "PITCHER_BB": {"FG"},
    "MONEYLINE": {"FG"},
    "RUN_LINE": {"FG"},
    "TOTALS": {"FG"},
    "NRFI": {"1ST"},
    "YRFI": {"1ST"},
}
PLAYER_PROP_MARKETS = {"HITS", "TOTAL_BASES", "PITCHER_BB"}
GAME_LEVEL_MARKETS = {"MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI"}
# MONEYLINE structurally has no line (it is a straight win/loss price) --
# every other supported market requires one.
MARKETS_WITHOUT_LINE = {"MONEYLINE"}


def _finite(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise QuoteBridgeError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise QuoteBridgeError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise QuoteBridgeError(f"{name} must be finite")
    return out


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if value is None:
        raise QuoteBridgeError("QUOTE_IDENTITY_INCOMPLETE")
    out = str(value).strip()
    if not out:
        raise QuoteBridgeError("QUOTE_IDENTITY_INCOMPLETE")
    return out


def validate_canonical_quote(raw: Mapping[str, Any], *, default_ttl_seconds: int = 300) -> dict[str, Any]:
    """Validate and canonicalize a quote regardless of ingestion path."""
    if not isinstance(raw, Mapping):
        raise QuoteBridgeError("offer must be an object")
    game_id = _required_text(raw, "game_id")
    market = _required_text(raw, "market").upper()
    if market in PLAYER_PROP_MARKETS:
        entity_id = _required_text(raw, "entity_id")
    else:
        # Game-level markets have no player-level entity; game_id + side
        # (+ line, where applicable) already uniquely identifies the quote.
        # entity_id stays present in the canonical shape for a stable schema
        # across all markets, but is not required to carry real content.
        entity_id = str(raw.get("entity_id") or "").strip()
    side = _required_text(raw, "side").upper()
    period = _required_text(raw, "period").upper()
    book_key = _required_text(raw, "book_key")
    raw_market_name = _required_text(raw, "raw_market_name")

    if market not in SUPPORTED_MARKETS:
        raise QuoteBridgeError(f"unsupported market: {market}")
    if side not in SUPPORTED_SIDES:
        raise QuoteBridgeError(f"unsupported side: {side}")
    if period not in SUPPORTED_PERIODS_BY_MARKET[market]:
        raise QuoteBridgeError("QUOTE_PERIOD_MODEL_MISMATCH")

    is_alternate = raw.get("is_alternate")
    if type(is_alternate) is not bool:
        raise QuoteBridgeError("QUOTE_IDENTITY_INCOMPLETE")

    if market in MARKETS_WITHOUT_LINE:
        if raw.get("line") is not None:
            raise QuoteBridgeError(f"{market} must not carry a line")
        line = None
    else:
        line = _finite("line", raw.get("line"))
    odds = _finite("american_odds", raw.get("american_odds"))
    if odds == 0 or -100 < odds < 100:
        raise QuoteBridgeError("american_odds must be <= -100 or >= 100")
    if odds != int(odds):
        raise QuoteBridgeError("american_odds must be an integer")

    retrieved_at = raw.get("retrieved_at")
    if isinstance(retrieved_at, str):
        try:
            retrieved = parse_timestamp(retrieved_at)
        except RuntimeInputError as exc:
            raise QuoteBridgeError("invalid retrieved_at") from exc
    elif isinstance(retrieved_at, datetime):
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise QuoteBridgeError("invalid retrieved_at")
        retrieved = retrieved_at
    else:
        raise QuoteBridgeError("retrieved_at must be an aware datetime or ISO timestamp string")

    ttl = raw.get("ttl_seconds", default_ttl_seconds)
    if isinstance(ttl, bool):
        raise QuoteBridgeError("ttl_seconds invalid")
    try:
        ttl = int(ttl)
    except (TypeError, ValueError) as exc:
        raise QuoteBridgeError("ttl_seconds invalid") from exc
    if ttl <= 0:
        raise QuoteBridgeError("ttl_seconds must be > 0")

    out = {
        "game_id": game_id,
        "period": period,
        "market": market,
        "entity_id": entity_id,
        "side": side,
        "line": line,
        "book_key": book_key,
        "retrieved_at": retrieved,
        "is_alternate": is_alternate,
        "raw_market_name": raw_market_name,
        "american_odds": int(odds),
        "ttl_seconds": ttl,
    }
    for key in ("sportsbook", "offer_id", "source_url"):
        if raw.get(key) not in (None, ""):
            out[key] = str(raw[key])
    return out


def normalize_offer(raw: Mapping[str, Any], *, default_ttl_seconds: int = 300) -> dict[str, Any]:
    return validate_canonical_quote(raw, default_ttl_seconds=default_ttl_seconds)


def normalize_offer_snapshot(data: Any, *, default_ttl_seconds: int = 300) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, list):
        raise QuoteBridgeError("offer snapshot must be a JSON list")
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str, str, bool, int]] = set()
    for i, raw in enumerate(data):
        try:
            q = validate_canonical_quote(raw, default_ttl_seconds=default_ttl_seconds)
            key = (
                q["game_id"], q["period"], q["market"], q["entity_id"],
                repr(q["line"]), q["side"], q["book_key"], q["is_alternate"],
                q["american_odds"],
            )
            if key in seen:
                raise QuoteBridgeError("duplicate sportsbook offer")
            seen.add(key)
            quotes.append(q)
        except Exception as exc:
            failures.append({"index": i, "reason": f"{type(exc).__name__}: {exc}"})
    return quotes, failures
