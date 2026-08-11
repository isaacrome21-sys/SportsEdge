"""Normalize timestamped sportsbook offers into canonical SportsEdge quotes."""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from .runtime import parse_timestamp, RuntimeInputError


class QuoteBridgeError(ValueError):
    pass


SUPPORTED_MARKETS = {"HITS", "TOTAL_BASES"}
SUPPORTED_SIDES = {"OVER", "UNDER"}


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


def normalize_offer(raw: Mapping[str, Any], *, default_ttl_seconds: int = 300) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise QuoteBridgeError("offer must be an object")
    try:
        game_id = str(raw["game_id"])
        market = str(raw["market"]).upper()
        entity_id = str(raw["entity_id"])
        side = str(raw["side"]).upper()
    except Exception as exc:
        raise QuoteBridgeError("offer missing canonical identity") from exc
    if not game_id or not entity_id:
        raise QuoteBridgeError("game_id/entity_id cannot be blank")
    if market not in SUPPORTED_MARKETS:
        raise QuoteBridgeError(f"unsupported market: {market}")
    if side not in SUPPORTED_SIDES:
        raise QuoteBridgeError(f"unsupported side: {side}")

    line = _finite("line", raw.get("line"))
    odds = _finite("american_odds", raw.get("american_odds"))
    if odds == 0 or -100 < odds < 100:
        raise QuoteBridgeError("american_odds must be <= -100 or >= 100")
    if odds != int(odds):
        raise QuoteBridgeError("american_odds must be an integer")

    retrieved_at = raw.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise QuoteBridgeError("retrieved_at must be an ISO timestamp string")
    try:
        retrieved = parse_timestamp(retrieved_at)
    except RuntimeInputError as exc:
        raise QuoteBridgeError("invalid retrieved_at") from exc

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
        "market": market,
        "entity_id": entity_id,
        "line": line,
        "side": side,
        "american_odds": int(odds),
        "retrieved_at": retrieved,
        "ttl_seconds": ttl,
    }
    for key in ("sportsbook", "offer_id", "source_url"):
        if raw.get(key) not in (None, ""):
            out[key] = str(raw[key])
    return out


def normalize_offer_snapshot(data: Any, *, default_ttl_seconds: int = 300) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize every provider offer and preserve malformed rows as failures."""
    if not isinstance(data, list):
        raise QuoteBridgeError("offer snapshot must be a JSON list")
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, int]] = set()
    for i, raw in enumerate(data):
        try:
            q = normalize_offer(raw, default_ttl_seconds=default_ttl_seconds)
            key = (q["game_id"], q["market"], q["entity_id"], repr(q["line"]), q["side"], q["american_odds"])
            if key in seen:
                raise QuoteBridgeError("duplicate sportsbook offer")
            seen.add(key)
            quotes.append(q)
        except Exception as exc:
            failures.append({"index": i, "reason": f"{type(exc).__name__}: {exc}"})
    return quotes, failures
