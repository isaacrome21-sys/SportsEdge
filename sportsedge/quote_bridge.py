"""Normalize timestamped sportsbook offers into canonical SportsEdge quotes.

Admission validates quote identity only. It never implies model promotion or betting
eligibility. All canonical prop labels route through the shared joint engines.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from .runtime import parse_timestamp, RuntimeInputError
from .hitter_joint_engine import HITTER_MARKETS
from .pitcher_joint_engine import PITCHER_MARKETS


class QuoteBridgeError(ValueError):
    pass


GAME_MARKETS = {
    "MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI",
    "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS",
}
COUNT_MARKETS = set(HITTER_MARKETS | PITCHER_MARKETS)
BINARY_MARKETS = {"PITCHER_RECORD_WIN", "FIRST_HOME_RUN"}
SUPPORTED_MARKETS = GAME_MARKETS | COUNT_MARKETS | BINARY_MARKETS

SUPPORTED_PERIODS_BY_MARKET = {
    **{m: {"FG"} for m in COUNT_MARKETS | BINARY_MARKETS | {"MONEYLINE", "RUN_LINE", "TOTALS"}},
    "NRFI": {"FG", "1ST", "1"},
    "YRFI": {"FG", "1ST", "1"},
    "F5_MONEYLINE": {"FG", "F5", "5"},
    "F5_RUN_LINE": {"FG", "F5", "5"},
    "F5_TOTALS": {"FG", "F5", "5"},
}

SIDE_BY_MARKET = {
    **{m: {"OVER", "UNDER"} for m in COUNT_MARKETS | {"TOTALS", "F5_TOTALS"}},
    **{m: {"YES", "NO"} for m in BINARY_MARKETS},
    "MONEYLINE": {"HOME", "AWAY", "HOME_ML", "AWAY_ML"},
    "F5_MONEYLINE": {"HOME", "AWAY", "HOME_ML", "AWAY_ML"},
    "RUN_LINE": {"HOME", "AWAY", "HOME_RL", "AWAY_RL"},
    "F5_RUN_LINE": {"HOME", "AWAY", "HOME_RL", "AWAY_RL"},
    "NRFI": {"YES", "NO", "NRFI"},
    "YRFI": {"YES", "NO", "YRFI"},
}

LINE_OPTIONAL_MARKETS = {"MONEYLINE", "F5_MONEYLINE", "NRFI", "YRFI"} | BINARY_MARKETS


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
    if not isinstance(raw, Mapping):
        raise QuoteBridgeError("offer must be an object")
    game_id = _required_text(raw, "game_id")
    market = _required_text(raw, "market").upper()
    entity_id = _required_text(raw, "entity_id")
    side = _required_text(raw, "side").upper()
    period = _required_text(raw, "period").upper()
    book_key = _required_text(raw, "book_key")
    raw_market_name = _required_text(raw, "raw_market_name")
    if market not in SUPPORTED_MARKETS:
        raise QuoteBridgeError(f"unsupported market: {market}")
    if side not in SIDE_BY_MARKET[market]:
        raise QuoteBridgeError(f"unsupported side for {market}: {side}")
    if period not in SUPPORTED_PERIODS_BY_MARKET[market]:
        raise QuoteBridgeError("QUOTE_PERIOD_MODEL_MISMATCH")
    is_alternate = raw.get("is_alternate")
    if type(is_alternate) is not bool:
        raise QuoteBridgeError("QUOTE_IDENTITY_INCOMPLETE")
    raw_line = raw.get("line")
    if raw_line is None and market in LINE_OPTIONAL_MARKETS:
        line = 0.0
    else:
        line = _finite("line", raw_line)
    if market in COUNT_MARKETS and line < 0:
        raise QuoteBridgeError("line must be >= 0")
    odds = _finite("american_odds", raw.get("american_odds"))
    if odds == 0 or -100 < odds < 100 or odds != int(odds):
        raise QuoteBridgeError("american_odds must be integer <= -100 or >= 100")
    retrieved_at = raw.get("retrieved_at")
    if isinstance(retrieved_at, str):
        try:
            retrieved = parse_timestamp(retrieved_at)
        except RuntimeInputError as exc:
            raise QuoteBridgeError("invalid retrieved_at") from exc
    elif isinstance(retrieved_at, datetime) and retrieved_at.tzinfo is not None and retrieved_at.utcoffset() is not None:
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
        "game_id": game_id, "period": period, "market": market, "entity_id": entity_id,
        "side": side, "line": line, "book_key": book_key, "retrieved_at": retrieved,
        "is_alternate": is_alternate, "raw_market_name": raw_market_name,
        "american_odds": int(odds), "ttl_seconds": ttl,
    }
    for key in ("sportsbook", "offer_id", "source_url", "selection"):
        if raw.get(key) not in (None, ""):
            out[key] = str(raw[key])
    return out


def normalize_offer(raw: Mapping[str, Any], *, default_ttl_seconds: int = 300) -> dict[str, Any]:
    return validate_canonical_quote(raw, default_ttl_seconds=default_ttl_seconds)


def normalize_offer_snapshot(data: Any, *, default_ttl_seconds: int = 300) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, list):
        raise QuoteBridgeError("offer snapshot must be a JSON list")
    quotes: list[dict[str, Any]] = []; failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str, str, bool, int]] = set()
    for i, raw in enumerate(data):
        try:
            q = validate_canonical_quote(raw, default_ttl_seconds=default_ttl_seconds)
            key = (q["game_id"], q["period"], q["market"], q["entity_id"], repr(q["line"]), q["side"], q["book_key"], q["is_alternate"], q["american_odds"])
            if key in seen:
                raise QuoteBridgeError("duplicate sportsbook offer")
            seen.add(key); quotes.append(q)
        except Exception as exc:
            failures.append({"index": i, "reason": f"{type(exc).__name__}: {exc}"})
    return quotes, failures
