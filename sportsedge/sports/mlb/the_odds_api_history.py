"""Normalize persisted The Odds API historical snapshots for MLB replay readiness.

This module performs no network access. It accepts exact persisted provider response
bytes plus their independently recorded SHA-256 and converts two real snapshots into
the generic decision/close contract consumed by paired_replay_readiness.

It cannot create Model_P, promotion evidence, edge floors, market eligibility, PASS,
or OFFICIAL status. It does not interpolate missing snapshots or reconstruct quotes.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping

from .paired_replay_readiness import validate_decision_close_pair

PROVIDER_SCHEMA = "MLB_THE_ODDS_API_HISTORICAL_SNAPSHOT_V1"
PROVENANCE = "the_odds_api_historical_snapshot"
SUPPORTED_MARKETS = {"h2h": "MONEYLINE", "spreads": "SPREAD", "totals": "TOTAL"}


class MLBTheOddsAPIHistoryError(ValueError):
    pass


def _require(value: bool, error: str) -> None:
    if not value:
        raise MLBTheOddsAPIHistoryError(error)


def _ts(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MLBTheOddsAPIHistoryError(f"MLB_TODDS_TIMESTAMP_INVALID:{field}") from exc
    _require(out.tzinfo is not None and out.utcoffset() is not None, f"MLB_TODDS_TIMESTAMP_TZ_REQUIRED:{field}")
    return out


def _hex64(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == 64 and all(c in "0123456789abcdef" for c in text), f"MLB_TODDS_SHA256_INVALID:{field}")
    return text


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _raw_payload(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    raw = snapshot.get("raw_bytes")
    _require(isinstance(raw, (bytes, bytearray)), "MLB_TODDS_RAW_BYTES_REQUIRED")
    raw_bytes = bytes(raw)
    expected = _hex64(snapshot.get("raw_sha256"), "raw_sha256")
    actual = sha256(raw_bytes).hexdigest()
    _require(actual == expected, "MLB_TODDS_RAW_SHA256_MISMATCH")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MLBTheOddsAPIHistoryError("MLB_TODDS_RAW_JSON_INVALID") from exc
    _require(isinstance(payload, Mapping), "MLB_TODDS_RESPONSE_MAPPING_REQUIRED")
    return dict(payload), actual


def _event_payload(response: Mapping[str, Any], event_id: str) -> Mapping[str, Any]:
    data = response.get("data")
    candidates: list[Mapping[str, Any]] = []
    if isinstance(data, Mapping):
        candidates = [data]
    elif isinstance(data, list):
        candidates = [row for row in data if isinstance(row, Mapping)]
    elif isinstance(response.get("id"), str):
        candidates = [response]
    _require(bool(candidates), "MLB_TODDS_EVENT_DATA_REQUIRED")
    matches = [row for row in candidates if str(row.get("id") or "") == event_id]
    _require(len(matches) == 1, "MLB_TODDS_EVENT_ID_MISMATCH")
    return matches[0]


def _market_key(market: str) -> str:
    requested = str(market or "").strip().upper()
    inverse = {value: key for key, value in SUPPORTED_MARKETS.items()}
    _require(requested in inverse, "MLB_TODDS_MARKET_UNSUPPORTED")
    return inverse[requested]


def _price(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBTheOddsAPIHistoryError("MLB_TODDS_PRICE_INVALID") from exc
    _require(isfinite(number) and number != 0.0, "MLB_TODDS_PRICE_INVALID")
    return number


def _point(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBTheOddsAPIHistoryError("MLB_TODDS_POINT_INVALID") from exc
    _require(isfinite(number), "MLB_TODDS_POINT_INVALID")
    return number


def _selection_and_opposite(
    outcomes: list[Mapping[str, Any]], *, market: str, selection: str, threshold: float | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    selected_name = str(selection or "").strip()
    _require(bool(selected_name), "MLB_TODDS_SELECTION_REQUIRED")

    if market == "MONEYLINE":
        matching = [o for o in outcomes if str(o.get("name") or "") == selected_name]
        _require(len(matching) == 1, "MLB_TODDS_SELECTION_NOT_FOUND")
        opposites = [o for o in outcomes if o is not matching[0]]
        _require(len(opposites) == 1, "MLB_TODDS_PAIRED_OPPOSITE_REQUIRED")
        _require(_point(matching[0].get("point")) is None, "MLB_TODDS_MONEYLINE_POINT_FORBIDDEN")
        return matching[0], opposites[0]

    _require(threshold is not None, "MLB_TODDS_THRESHOLD_REQUIRED")
    matching = [
        o for o in outcomes
        if str(o.get("name") or "") == selected_name and _point(o.get("point")) == threshold
    ]
    _require(len(matching) == 1, "MLB_TODDS_SELECTION_THRESHOLD_NOT_FOUND")

    if market == "SPREAD":
        opposites = [
            o for o in outcomes
            if o is not matching[0] and _point(o.get("point")) == -threshold
        ]
    else:
        want = "Under" if selected_name == "Over" else "Over" if selected_name == "Under" else ""
        _require(bool(want), "MLB_TODDS_TOTAL_SELECTION_INVALID")
        opposites = [
            o for o in outcomes
            if str(o.get("name") or "") == want and _point(o.get("point")) == threshold
        ]
    _require(len(opposites) == 1, "MLB_TODDS_PAIRED_OPPOSITE_REQUIRED")
    return matching[0], opposites[0]


def normalize_snapshot_quote(
    snapshot: Mapping[str, Any], *, event_id: str, book: str, market: str,
    selection: str, threshold: float | None,
) -> dict[str, Any]:
    _require(str(snapshot.get("schema") or "") == PROVIDER_SCHEMA, "MLB_TODDS_SCHEMA_INVALID")
    _require(str(snapshot.get("provenance") or "").lower() == PROVENANCE, "MLB_TODDS_PROVENANCE_INVALID")
    _require(not bool(snapshot.get("interpolated")), "MLB_TODDS_INTERPOLATION_FORBIDDEN")
    _require(not bool(snapshot.get("reconstructed")), "MLB_TODDS_RECONSTRUCTION_FORBIDDEN")

    payload, raw_sha = _raw_payload(snapshot)
    snapshot_ts = _ts(payload.get("timestamp"), "provider.timestamp")
    requested_at = snapshot.get("requested_at")
    if requested_at is not None:
        requested_ts = _ts(requested_at, "requested_at")
        _require(snapshot_ts <= requested_ts, "MLB_TODDS_SNAPSHOT_AFTER_REQUESTED_AT")

    event = _event_payload(payload, event_id)
    commence = _ts(event.get("commence_time"), "event.commence_time")
    _require(snapshot_ts < commence, "MLB_TODDS_SNAPSHOT_AFTER_START")

    bookmakers = event.get("bookmakers")
    _require(isinstance(bookmakers, list), "MLB_TODDS_BOOKMAKERS_REQUIRED")
    books = [row for row in bookmakers if isinstance(row, Mapping) and str(row.get("key") or "") == book]
    _require(len(books) == 1, "MLB_TODDS_BOOK_NOT_FOUND")

    provider_market = _market_key(market)
    markets = books[0].get("markets")
    _require(isinstance(markets, list), "MLB_TODDS_MARKETS_REQUIRED")
    market_rows = [row for row in markets if isinstance(row, Mapping) and str(row.get("key") or "") == provider_market]
    _require(len(market_rows) == 1, "MLB_TODDS_MARKET_NOT_FOUND")
    outcomes_raw = market_rows[0].get("outcomes")
    _require(isinstance(outcomes_raw, list), "MLB_TODDS_OUTCOMES_REQUIRED")
    outcomes = [row for row in outcomes_raw if isinstance(row, Mapping)]
    selected, opposite = _selection_and_opposite(
        outcomes, market=str(market).upper(), selection=selection, threshold=threshold,
    )

    return {
        "event_id": event_id,
        "market": str(market).upper(),
        "selection": selection,
        "book": book,
        "threshold": threshold,
        "event_start": commence.isoformat(),
        "observed_at": snapshot_ts.isoformat(),
        "price": _price(selected.get("price")),
        "opposite_selection": str(opposite.get("name") or ""),
        "opposite_price": _price(opposite.get("price")),
        "source_sha256": raw_sha,
        "provenance": PROVENANCE,
        "provider_market": provider_market,
    }


def normalize_decision_close_pair(
    decision_snapshot: Mapping[str, Any], close_snapshot: Mapping[str, Any], *,
    event_id: str, book: str, market: str, selection: str, threshold: float | None = None,
) -> dict[str, Any]:
    decision = normalize_snapshot_quote(
        decision_snapshot, event_id=event_id, book=book, market=market,
        selection=selection, threshold=threshold,
    )
    close = normalize_snapshot_quote(
        close_snapshot, event_id=event_id, book=book, market=market,
        selection=selection, threshold=threshold,
    )
    _require(decision["event_start"] == close["event_start"], "MLB_TODDS_EVENT_START_MISMATCH")

    generic_pair = {
        "event_start": decision["event_start"],
        "decision": {k: decision[k] for k in ("event_id", "market", "selection", "book", "observed_at", "price", "source_sha256", "provenance")},
        "close": {k: close[k] for k in ("event_id", "market", "selection", "book", "observed_at", "price", "source_sha256", "provenance")},
    }
    validated = validate_decision_close_pair(generic_pair)
    evidence = {
        "schema": PROVIDER_SCHEMA,
        "provider": "The Odds API",
        "promotion_authority": False,
        "may_change_market_eligibility": False,
        "normalized_pair": validated,
        "threshold": threshold,
        "decision_opposite_selection": decision["opposite_selection"],
        "decision_opposite_price": decision["opposite_price"],
        "close_opposite_selection": close["opposite_selection"],
        "close_opposite_price": close["opposite_price"],
        "decision_raw_sha256": decision["source_sha256"],
        "close_raw_sha256": close["source_sha256"],
    }
    evidence["provider_evidence_sha256"] = _canonical_sha256(evidence)
    return evidence
