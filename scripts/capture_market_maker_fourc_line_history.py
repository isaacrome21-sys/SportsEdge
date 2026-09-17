#!/usr/bin/env python3
"""Normalize a provenance-bound 4C Odds line-history capsule for SportsEdge.

This importer does not scrape 4C Odds and does not claim to receive native
sportsbook timestamps. It accepts a deliberately small capsule created from a
4C line-history export or retained source capture, binds the normalized rows to
that capture's SHA-256, and writes zero-authority MARKET_MAKER_RADAR_V1 rows.

4C book names are namespaced (``fourc_pinnacle`` etc.) so aggregator history can
never blend with SportsEdge's native/direct book observations. The displayed
4C move time is stored as ``captured_at`` because it is the aggregator's
observation time; ``book_last_update`` remains null.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

UTC = timezone.utc
SCHEMA_VERSION = "FOURC_LINE_HISTORY_CAPSULE_V1"
SOURCE_CLASS = "FOURC_LINE_HISTORY_V1"
POLICY_ID = "MARKET_MAKER_RADAR_V1"
EVIDENCE_CLASS = "LAYER_B_HARD_MARKET_DIAGNOSTIC"
ALLOWED_MARKETS = {"h2h", "spreads", "totals"}
BOOK_ALIASES = {
    "pinnacle": "fourc_pinnacle",
    "pinny": "fourc_pinnacle",
    "draftkings": "fourc_draftkings",
    "draft kings": "fourc_draftkings",
    "dk": "fourc_draftkings",
    "fanduel": "fourc_fanduel",
    "fan duel": "fourc_fanduel",
    "fd": "fourc_fanduel",
}


class FourCImportError(RuntimeError):
    """Fail-closed 4C line-history import error."""


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise FourCImportError("FOURC_TIMESTAMP_MISSING")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise FourCImportError("FOURC_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FourCImportError("FOURC_TIMESTAMP_NAIVE")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: Any, *, code: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise FourCImportError(code)
    return text


def _number(value: Any, *, code: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FourCImportError(code) from exc
    if not math.isfinite(result):
        raise FourCImportError(code)
    return result


def _american_price(value: Any) -> int:
    number = _number(value, code="FOURC_PRICE_INVALID")
    if number == 0 or not number.is_integer():
        raise FourCImportError("FOURC_PRICE_INVALID")
    return int(number)


def _book(value: Any) -> str:
    key = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if key not in BOOK_ALIASES:
        raise FourCImportError(f"FOURC_BOOK_UNSUPPORTED:{value}")
    return BOOK_ALIASES[key]


def _designation(value: Any, market: str) -> str:
    designation = str(value or "").strip().lower()
    allowed = {"home", "away"} if market in {"h2h", "spreads"} else {"over", "under"}
    if designation not in allowed:
        raise FourCImportError("FOURC_DESIGNATION_INVALID")
    return designation


def _event(payload: Mapping[str, Any]) -> dict[str, str]:
    event = payload.get("event")
    if not isinstance(event, Mapping):
        raise FourCImportError("FOURC_EVENT_MISSING")
    required = ("source_event_key", "sport_key", "home_team", "away_team", "commence_time")
    values = {key: str(event.get(key) or "").strip() for key in required}
    if any(not values[key] for key in required):
        raise FourCImportError("FOURC_EVENT_FIELD_MISSING")
    if values["home_team"].casefold() == values["away_team"].casefold():
        raise FourCImportError("FOURC_EVENT_TEAMS_DUPLICATE")
    values["commence_time"] = _iso(_parse_ts(values["commence_time"]))
    return values


def normalize_capsule(
    payload: Mapping[str, Any],
    *,
    capsule_sha256: str,
    ingested_at: datetime,
) -> list[dict[str, Any]]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise FourCImportError("FOURC_SCHEMA_VERSION_MISMATCH")
    if str(payload.get("source") or "").strip().lower() not in {"4c", "4codds", "4c odds"}:
        raise FourCImportError("FOURC_SOURCE_MISMATCH")
    source_url = str(payload.get("source_url") or "").strip()
    if not source_url.startswith("https://www.4codds.com/") and not source_url.startswith("https://4codds.com/"):
        raise FourCImportError("FOURC_SOURCE_URL_INVALID")
    source_capture_sha256 = _require_sha256(
        payload.get("source_capture_sha256"), code="FOURC_SOURCE_CAPTURE_SHA256_INVALID"
    )
    capsule_sha256 = _require_sha256(capsule_sha256, code="FOURC_CAPSULE_SHA256_INVALID")
    event = _event(payload)
    market = str(payload.get("market") or "").strip().lower()
    if market not in ALLOWED_MARKETS:
        raise FourCImportError("FOURC_MARKET_UNSUPPORTED")
    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        raise FourCImportError("FOURC_OBSERVATIONS_MISSING")

    event_id = f"fourc:{event['sport_key']}:{event['source_event_key']}"
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for idx, raw in enumerate(observations):
        if not isinstance(raw, Mapping):
            raise FourCImportError("FOURC_OBSERVATION_INVALID")
        book = _book(raw.get("book"))
        designation = _designation(raw.get("designation"), market)
        observed_at = _iso(_parse_ts(raw.get("observed_at")))
        price = _american_price(raw.get("price_american"))
        point: float | None = None
        if market == "h2h":
            if raw.get("point") not in (None, ""):
                raise FourCImportError("FOURC_H2H_POINT_FORBIDDEN")
        else:
            point = _number(raw.get("point"), code="FOURC_POINT_INVALID")
        identity = (book, designation, observed_at, point, price)
        if identity in seen:
            raise FourCImportError("FOURC_DUPLICATE_OBSERVATION")
        seen.add(identity)

        if designation == "home":
            outcome = event["home_team"]
        elif designation == "away":
            outcome = event["away_team"]
        elif designation == "over":
            outcome = "Over"
        else:
            outcome = "Under"

        capture_material = f"{capsule_sha256}|{idx}|{book}|{observed_at}|{market}|{designation}"
        capture_id = "fourc-" + hashlib.sha256(capture_material.encode("utf-8")).hexdigest()[:24]
        rows.append(
            {
                "schema_version": "MARKET_MAKER_RADAR_OBSERVATION_V1",
                "policy_id": POLICY_ID,
                "evidence_class": EVIDENCE_CLASS,
                "source_class": SOURCE_CLASS,
                "transport": "PROVENANCE_BOUND_CAPSULE_IMPORT",
                "source_url": source_url,
                "source_event_key": event["source_event_key"],
                "source_capture_sha256": source_capture_sha256,
                "capsule_sha256": capsule_sha256,
                "capture_id": capture_id,
                "sport_key": event["sport_key"],
                "event_id": event_id,
                "home_team": event["home_team"],
                "away_team": event["away_team"],
                "commence_time": event["commence_time"],
                "book": book,
                "market": market,
                "outcome": outcome,
                "designation": designation,
                "point": point,
                "price_american": price,
                "captured_at": observed_at,
                "ingested_at": _iso(ingested_at),
                "book_last_update": None,
                "timestamp_source": "FOURC_DISPLAYED_MOVE_TIME",
                "provider_quote_timestamp_available": False,
                "aggregator_move_timestamp_available": True,
                "native_sportsbook_identity_authority": False,
                "draftkings_evidence_authority": False,
                "model_p_authority": False,
                "truth_gate_input": False,
                "promotion_authority": False,
                "eligibility_authority": False,
                "staking_authority": False,
                "official_authority": False,
                "evidence_clock_authority": False,
                "wager_placement_authority": False,
            }
        )
    rows.sort(key=lambda row: (row["captured_at"], row["book"], row["outcome"], row["capture_id"]))
    return rows


def import_file(input_path: Path, *, ingested_at: datetime) -> tuple[list[dict[str, Any]], str]:
    raw = input_path.read_bytes()
    capsule_sha256 = _sha256_bytes(raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FourCImportError("FOURC_CAPSULE_JSON_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise FourCImportError("FOURC_CAPSULE_NOT_OBJECT")
    return normalize_capsule(payload, capsule_sha256=capsule_sha256, ingested_at=ingested_at), capsule_sha256


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ingested-at", default=None)
    args = parser.parse_args(argv)

    ingested_at = _parse_ts(args.ingested_at) if args.ingested_at else datetime.now(UTC)
    rows, capsule_sha256 = import_file(Path(args.input), ingested_at=ingested_at)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({
        "state": "IMPORTED_ZERO_AUTHORITY",
        "source_class": SOURCE_CLASS,
        "capsule_sha256": capsule_sha256,
        "rows": len(rows),
        "out": str(target),
        "official_authority": False,
        "truth_gate_input": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
