"""Materialize immutable The Odds API MLB snapshots into canonical SportsEdge quotes.

The materializer is deliberately fail-closed. It verifies the persisted raw-byte
SHA-256, admits only documented direct semantic mappings, preserves provider/event
identity, and never derives an unsupported canonical market from a nearby market.

It does not create Model_P, replay decisions, promotion evidence, edge floors,
eligibility, staking, Truth Gate PASS, or OFFICIAL status.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping

from sportsedge.quote_bridge import QuoteBridgeError, validate_canonical_quote
from .provider_market_catalog import (
    BINARY_ENTITY_MARKETS,
    F5_MARKETS,
    MARKET_BY_PROVIDER_KEY,
    NO_DIRECT_PROVIDER_KEY,
    PROVIDER,
    PROVIDER_KEY_BY_MARKET,
    TEAM_SIDE_MARKETS,
    TEAM_TOTAL_MARKETS,
)

SCHEMA_VERSION = "MLB_THE_ODDS_API_CANONICAL_MATERIALIZATION_V1"


class MLBTheOddsAPIMaterializationError(ValueError):
    pass


def _require(value: bool, error: str) -> None:
    if not value:
        raise MLBTheOddsAPIMaterializationError(error)


def _aware_iso(value: Any, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MLBTheOddsAPIMaterializationError(f"MLB_TODDS_MATERIALIZE_TIMESTAMP_INVALID:{field}") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"MLB_TODDS_MATERIALIZE_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed.isoformat()


def _hex64(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == 64 and all(c in "0123456789abcdef" for c in text), f"MLB_TODDS_MATERIALIZE_SHA256_INVALID:{field}")
    return text


def _price(value: Any) -> int:
    if isinstance(value, bool):
        raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_PRICE_INVALID")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_PRICE_INVALID") from exc
    _require(isfinite(number) and number == int(number), "MLB_TODDS_MATERIALIZE_PRICE_INVALID")
    odds = int(number)
    _require(odds <= -100 or odds >= 100, "MLB_TODDS_MATERIALIZE_PRICE_INVALID")
    return odds


def _line(value: Any, *, required: bool) -> float:
    if value is None:
        if required:
            raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_LINE_REQUIRED")
        return 0.0
    if isinstance(value, bool):
        raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_LINE_INVALID")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_LINE_INVALID") from exc
    _require(isfinite(out), "MLB_TODDS_MATERIALIZE_LINE_INVALID")
    return out


def _events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    if isinstance(data, Mapping):
        return [data]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if isinstance(payload.get("id"), str):
        return [payload]
    raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_EVENT_DATA_REQUIRED")


def _side_entity_line(
    *, market: str, outcome: Mapping[str, Any], event_id: str, home_team: str, away_team: str,
) -> tuple[str, str, float]:
    raw_name = str(outcome.get("name") or "").strip()
    description = str(outcome.get("description") or "").strip()
    _require(bool(raw_name), "MLB_TODDS_MATERIALIZE_OUTCOME_NAME_REQUIRED")

    if market in TEAM_SIDE_MARKETS:
        if raw_name == home_team:
            side, entity = "HOME", home_team
        elif raw_name == away_team:
            side, entity = "AWAY", away_team
        else:
            raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_TEAM_SIDE_UNRESOLVED")
        needs_line = market in {"RUN_LINE", "F5_RUN_LINE"}
        return side, entity, _line(outcome.get("point"), required=needs_line)

    if market in BINARY_ENTITY_MARKETS:
        side = raw_name.upper()
        _require(side in {"YES", "NO"}, "MLB_TODDS_MATERIALIZE_BINARY_SIDE_INVALID")
        _require(bool(description), "MLB_TODDS_MATERIALIZE_ENTITY_DESCRIPTION_REQUIRED")
        return side, description, _line(outcome.get("point"), required=False)

    side = raw_name.upper()
    _require(side in {"OVER", "UNDER"}, "MLB_TODDS_MATERIALIZE_OVER_UNDER_SIDE_INVALID")
    if market in TEAM_TOTAL_MARKETS:
        _require(bool(description), "MLB_TODDS_MATERIALIZE_TEAM_TOTAL_ENTITY_REQUIRED")
        entity = description
    elif market in {"TOTALS", "F5_TOTALS"}:
        entity = event_id
    else:
        _require(bool(description), "MLB_TODDS_MATERIALIZE_ENTITY_DESCRIPTION_REQUIRED")
        entity = description
    return side, entity, _line(outcome.get("point"), required=True)


def _period(market: str) -> str:
    return "F5" if market in F5_MARKETS else "FG"


def materialize_persisted_snapshot(
    raw_bytes: bytes, *, source_sha256: str, ttl_seconds: int = 180,
) -> dict[str, Any]:
    """Convert one exact persisted provider response into canonical quote rows.

    The returned rows are identity-valid canonical quotes only. Event/player entity
    reconciliation to SportsEdge model IDs remains a separate PIT join concern.
    """
    _require(isinstance(raw_bytes, (bytes, bytearray)), "MLB_TODDS_MATERIALIZE_RAW_BYTES_REQUIRED")
    raw = bytes(raw_bytes)
    expected_sha = _hex64(source_sha256, "source_sha256")
    actual_sha = sha256(raw).hexdigest()
    _require(actual_sha == expected_sha, "MLB_TODDS_MATERIALIZE_SHA256_MISMATCH")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MLBTheOddsAPIMaterializationError("MLB_TODDS_MATERIALIZE_JSON_INVALID") from exc
    _require(isinstance(payload, Mapping), "MLB_TODDS_MATERIALIZE_MAPPING_REQUIRED")
    observed_at = _aware_iso(payload.get("timestamp"), "provider.timestamp")

    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    ignored_provider_markets: Counter[str] = Counter()
    direct_markets_seen: set[str] = set()

    for event_index, event in enumerate(_events(payload)):
        event_id = str(event.get("id") or "").strip()
        home_team = str(event.get("home_team") or "").strip()
        away_team = str(event.get("away_team") or "").strip()
        if not event_id or not home_team or not away_team:
            failures.append({"event_index": event_index, "reason": "EVENT_IDENTITY_INCOMPLETE"})
            continue
        bookmakers = event.get("bookmakers")
        if not isinstance(bookmakers, list):
            failures.append({"event_index": event_index, "reason": "BOOKMAKERS_LIST_REQUIRED"})
            continue
        for book_index, book in enumerate(bookmakers):
            if not isinstance(book, Mapping):
                failures.append({"event_index": event_index, "book_index": book_index, "reason": "BOOK_MAPPING_REQUIRED"})
                continue
            book_key = str(book.get("key") or "").strip().lower()
            markets = book.get("markets")
            if not book_key or not isinstance(markets, list):
                failures.append({"event_index": event_index, "book_index": book_index, "reason": "BOOK_IDENTITY_OR_MARKETS_MISSING"})
                continue
            for market_index, provider_market in enumerate(markets):
                if not isinstance(provider_market, Mapping):
                    failures.append({"event_index": event_index, "book": book_key, "market_index": market_index, "reason": "MARKET_MAPPING_REQUIRED"})
                    continue
                provider_key = str(provider_market.get("key") or "").strip()
                canonical_market = MARKET_BY_PROVIDER_KEY.get(provider_key)
                if canonical_market is None:
                    if provider_key:
                        ignored_provider_markets[provider_key] += 1
                    continue
                direct_markets_seen.add(canonical_market)
                outcomes = provider_market.get("outcomes")
                if not isinstance(outcomes, list):
                    failures.append({"event_id": event_id, "book": book_key, "market": canonical_market, "reason": "OUTCOMES_LIST_REQUIRED"})
                    continue
                for outcome_index, outcome in enumerate(outcomes):
                    if not isinstance(outcome, Mapping):
                        failures.append({"event_id": event_id, "book": book_key, "market": canonical_market, "outcome_index": outcome_index, "reason": "OUTCOME_MAPPING_REQUIRED"})
                        continue
                    try:
                        side, entity_id, line = _side_entity_line(
                            market=canonical_market,
                            outcome=outcome,
                            event_id=event_id,
                            home_team=home_team,
                            away_team=away_team,
                        )
                        quote = validate_canonical_quote({
                            "game_id": event_id,
                            "period": _period(canonical_market),
                            "market": canonical_market,
                            "entity_id": entity_id,
                            "side": side,
                            "line": line,
                            "book_key": book_key,
                            "sportsbook": str(book.get("title") or book_key),
                            "retrieved_at": observed_at,
                            "is_alternate": False,
                            "raw_market_name": provider_key,
                            "american_odds": _price(outcome.get("price")),
                            "ttl_seconds": ttl_seconds,
                            "selection": str(outcome.get("name") or ""),
                            "source_provider": PROVIDER,
                            "source_event_id": event_id,
                            "source_home_team_name": home_team,
                            "source_away_team_name": away_team,
                        }, default_ttl_seconds=ttl_seconds)
                    except (MLBTheOddsAPIMaterializationError, QuoteBridgeError) as exc:
                        failures.append({
                            "event_id": event_id,
                            "book": book_key,
                            "market": canonical_market,
                            "outcome_index": outcome_index,
                            "reason": str(exc),
                        })
                        continue
                    quote["provider_snapshot_sha256"] = actual_sha
                    quotes.append(quote)

    counts = Counter(str(quote["market"]) for quote in quotes)
    if failures:
        status = "BLOCKED_PROVIDER_SNAPSHOT"
    elif quotes:
        status = "MATERIALIZED"
    else:
        status = "BLOCKED_NO_CANONICAL_QUOTES"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "provider": PROVIDER,
        "provider_snapshot_sha256": actual_sha,
        "observed_at": observed_at,
        "quote_count": len(quotes),
        "quote_count_by_market": dict(sorted(counts.items())),
        "direct_markets_seen": sorted(direct_markets_seen),
        "direct_markets_not_seen": sorted(set(PROVIDER_KEY_BY_MARKET) - direct_markets_seen),
        "no_direct_provider_markets": dict(sorted(NO_DIRECT_PROVIDER_KEY.items())),
        "ignored_provider_markets": dict(sorted(ignored_provider_markets.items())),
        "failure_count": len(failures),
        "failures": failures,
        "quotes": quotes,
        "promotion_authority": False,
        "may_change_market_eligibility": False,
        "model_p_authority": False,
    }
