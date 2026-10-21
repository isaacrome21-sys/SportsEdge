"""OddsPapi v4 historical-odds *candidate* admission, never market authority.

Official v4 endpoint /historical-odds returns fixtureId and nested
bookmakers -> markets -> outcomes -> players -> historical quotes.
Provider documentation currently describes archive since January 2026.

One request per CLI invocation: provider's documented 5000ms cooldown
is respected by an external orchestrator, not bypassed with retries.
Existing repo secret SPORTSEDGE_ODDSPAPI_KEY is used only in the request.
Never log the URL (apiKey is a query parameter), response body, key, IP
or any exception text containing URL/credentials.

This is a research-only, fail-closed candidate parser. No quote is a
certified DK observation, actual-first-play close, executable two-sided
market, or admitted model baseline until independently pinned provider
catalog, fixture/team identity, market map and source archive are
verified. No result can change deployment, stakes or "PLAY".
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.oddspapi.io/v4/historical-odds"
SECRET = "SPORTSEDGE_ODDSPAPI_KEY"
VERSION = "ODDSPAPI_V4_HISTORY_CANDIDATE_V1"
CATALOG_VERSION = "ODDSPAPI_MARKET_ID_MAP_V1"
EARLIEST_HISTORY_UTC = datetime(2026, 1, 1, tzinfo=timezone.utc)
PAIR_SPAN_SECONDS = 150
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
HASH = re.compile(r"^[a-fA-F0-9]{64}$")
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
SAFE_BOOK = re.compile(r"^[a-z0-9_-]{2,80}$")
SIDES = frozenset({
    "HOME", "AWAY", "TIE", "OVER", "UNDER", "YES", "NO", "EXACTLY",
})


class OddsPapiCandidateError(ValueError):
    """Error messages are sanitized codes, never provider response text."""


def _iso(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OddsPapiCandidateError(f"{field}_UTC_REQUIRED")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OddsPapiCandidateError(f"{field}_UTC_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise OddsPapiCandidateError(f"{field}_UTC_OFFSET_REQUIRED")
    return result.astimezone(timezone.utc)


def _sha(data: Any, field: str) -> str:
    if not isinstance(data, str) or not HASH.fullmatch(data):
        raise OddsPapiCandidateError(f"{field}_SHA256_REQUIRED")
    return data.lower()


def _canon(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")).hexdigest()


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise OddsPapiCandidateError(f"{field}_ID_INVALID")
    return value


def _validate_anchor(anchor: Mapping[str, Any]) -> tuple[str, datetime]:
    if not isinstance(anchor, Mapping):
        raise OddsPapiCandidateError("INDEPENDENT_FIXTURE_ANCHOR_REQUIRED")
    fixture = _safe_id(anchor.get("fixtureId"), "FIXTURE")
    start = _iso(anchor.get("scheduled_start_utc"), "FIXTURE_START")
    if start < EARLIEST_HISTORY_UTC:
        raise OddsPapiCandidateError("NO_PROVIDER_HISTORICAL_COVERAGE_PRE_2026")
    if not isinstance(anchor.get("canonical_event_id"), str) or (
            not anchor["canonical_event_id"].strip()):
        raise OddsPapiCandidateError("CANONICAL_EVENT_ID_REQUIRED")
    # A hash string is not proof of independent verification.
    _sha(anchor.get("fixture_anchor_sha256"), "FIXTURE_ANCHOR")
    return fixture, start


def _validate_mapping(mapping: Mapping[str, Any],
                      fixture: str) -> tuple[str, str, dict[str, str]]:
    if not isinstance(mapping, Mapping) or mapping.get("version") != CATALOG_VERSION:
        raise OddsPapiCandidateError("VERSIONED_MARKET_MAPPING_REQUIRED")
    if mapping.get("fixtureId") != fixture:
        raise OddsPapiCandidateError("MARKET_MAPPING_FIXTURE_MISMATCH")
    bookmaker = mapping.get("bookmaker")
    if not isinstance(bookmaker, str) or not SAFE_BOOK.fullmatch(bookmaker):
        raise OddsPapiCandidateError("BOOKMAKER_SLUG_REQUIRED")
    market_id = _safe_id(str(mapping.get("market_id", "")), "MARKET")
    _sha(mapping.get("market_catalog_sha256"), "MARKET_CATALOG")
    if not isinstance(mapping.get("canonical_market"), str) or (
            not mapping["canonical_market"].strip()):
        raise OddsPapiCandidateError("CANONICAL_MARKET_ID_REQUIRED")
    if mapping.get("player_id") != "0":
        # Player market identity needs a separately reviewed contract.
        raise OddsPapiCandidateError("PLAYER_SUBJECT_BINDING_NOT_ADMITTED")
    sides = mapping.get("selection_by_outcome_id")
    if not isinstance(sides, Mapping) or len(sides) not in (2, 3):
        raise OddsPapiCandidateError("COMPLETE_TWO_OR_THREE_WAY_MAPPING_REQUIRED")
    normalized: dict[str, str] = {}
    for raw_id, raw_side in sides.items():
        key = _safe_id(raw_id, "OUTCOME")
        side = str(raw_side or "").upper()
        if side not in SIDES or side in normalized.values():
            raise OddsPapiCandidateError("OUTCOME_SIDE_COLLISION_OR_UNKNOWN")
        normalized[key] = side
    if frozenset(normalized.values()) not in (
            frozenset({"HOME", "AWAY"}),
            frozenset({"HOME", "AWAY", "TIE"}),
            frozenset({"OVER", "UNDER"}),
            frozenset({"YES", "NO"}),
            frozenset({"OVER", "UNDER", "EXACTLY"})):
        raise OddsPapiCandidateError("OUTCOME_PARTITION_NOT_RECOGNIZED")
    return bookmaker, market_id, normalized


def _best_snapshot(values: Any, start: datetime):
    if not isinstance(values, list):
        raise OddsPapiCandidateError("HISTORY_PLAYER_ARRAY_REQUIRED")
    eligible = []
    poststart = 0
    for entry in values:
        if not isinstance(entry, Mapping):
            raise OddsPapiCandidateError("HISTORY_ENTRY_OBJECT_REQUIRED")
        timestamp = _iso(entry.get("createdAt"), "ODDSPAPI_QUOTE")
        if timestamp >= start:
            poststart += 1
            continue
        try:
            price = float(entry["price"])
        except (KeyError, ValueError, TypeError) as exc:
            raise OddsPapiCandidateError("DECIMAL_PRICE_REQUIRED") from exc
        if not math.isfinite(price) or price <= 1 or price > 100000:
            raise OddsPapiCandidateError("DECIMAL_PRICE_OUT_OF_BOUNDS")
        if "active" in entry and not isinstance(entry["active"], bool):
            raise OddsPapiCandidateError("HISTORICAL_ACTIVE_FLAG_INVALID")
        quote_id = entry.get("id")
        if quote_id is not None and (isinstance(quote_id, bool) or
                                      not isinstance(quote_id, int) or
                                      quote_id < 0):
            raise OddsPapiCandidateError("HISTORICAL_QUOTE_ID_INVALID")
        eligible.append({
            "created_at_utc": timestamp.isoformat(),
            "decimal_price": price,
            "historical_active_flag": entry.get("active"),
            "quote_id": quote_id,
        })
    if not eligible:
        return None, poststart
    eligible.sort(key=lambda x: (x["created_at_utc"],
                                 x["quote_id"] if x["quote_id"] is not None else -1))
    if len(eligible) >= 2 and eligible[-1]["created_at_utc"] == (
            eligible[-2]["created_at_utc"]) and eligible[-1]["decimal_price"] != (
            eligible[-2]["decimal_price"]):
        raise OddsPapiCandidateError("AMBIGUOUS_SAME_TIME_PRICE_CONFLICT")
    return eligible[-1], poststart


def inspect_historical_payload(payload: Mapping[str, Any],
                               anchor: Mapping[str, Any],
                               mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return only *unverified structural candidates*, never booked quotes.

    The caller must compare fixture/catalog/market IDs against admitted
    provider records and the true first play before downstream use.
    Historical pregame selection is NOT a certified closing line.
    """
    fixture, start = _validate_anchor(anchor)
    book, market_id, sides = _validate_mapping(mapping, fixture)
    if not isinstance(payload, Mapping) or payload.get("fixtureId") != fixture:
        raise OddsPapiCandidateError("ODDSPAPI_RESPONSE_FIXTURE_MISMATCH")
    bookmakers = payload.get("bookmakers")
    if not isinstance(bookmakers, Mapping):
        raise OddsPapiCandidateError("ODDSPAPI_RESPONSE_BOOKMAKERS_MISSING")
    obj = bookmakers.get(book)
    if not isinstance(obj, Mapping):
        raise OddsPapiCandidateError("ODDSPAPI_BOOKMAKER_NOT_RETURNED")
    markets = obj.get("markets")
    if not isinstance(markets, Mapping):
        raise OddsPapiCandidateError("ODDSPAPI_MARKET_MAP_MISSING")
    market = markets.get(market_id)
    if not isinstance(market, Mapping) or not isinstance(
            market.get("outcomes"), Mapping):
        raise OddsPapiCandidateError("ODDSPAPI_REQUESTED_MARKET_MISSING")
    outcome_obj = market["outcomes"]
    if set(outcome_obj) != set(sides):
        raise OddsPapiCandidateError("ODDSPAPI_OUTCOME_SET_MISMATCH")
    rows = []
    poststarts = 0
    for oid, side in sorted(sides.items()):
        outcome = outcome_obj[oid]
        if not isinstance(outcome, Mapping):
            raise OddsPapiCandidateError("ODDSPAPI_OUTCOME_OBJECT_REQUIRED")
        players = outcome.get("players")
        if not isinstance(players, Mapping) or set(players) != {"0"}:
            raise OddsPapiCandidateError("ODDSPAPI_UNVERIFIED_PLAYER_SET")
        best, count = _best_snapshot(players["0"], start)
        poststarts += count
        if best is None:
            raise OddsPapiCandidateError("NO_COMPLETE_PREGAME_OUTCOME_PAIR")
        rows.append({
            "outcome_id": oid, "selection": side,
            **best,
        })
    timestamps = [_iso(row["created_at_utc"], "ODDSPAPI_QUOTE")
                  for row in rows]
    span = (max(timestamps)-min(timestamps)).total_seconds()
    if span > PAIR_SPAN_SECONDS:
        raise OddsPapiCandidateError("PREGAME_OUTCOME_CAPTURE_SPAN_EXCEEDS_150S")
    material = {
        "version": VERSION,
        "fixtureId": fixture, "canonical_event_id": anchor["canonical_event_id"],
        "fixture_anchor_sha256": _sha(
            anchor["fixture_anchor_sha256"], "FIXTURE_ANCHOR"),
        "bookmaker": book, "market_id": market_id,
        "canonical_market_unverified": mapping["canonical_market"],
        "market_catalog_sha256": _sha(
            mapping["market_catalog_sha256"], "MARKET_CATALOG"),
        "source_payload_sha256": _canon(payload),
        "scheduled_start_utc": start.isoformat(),
        "source_selection_rows": rows,
        "capture_span_seconds": span,
        "post_start_entries_ignored": poststarts,
    }
    return {
        "status": "STRUCTURAL_CANDIDATE_UNVERIFIED",
        "provider": "ODDSPAPI_V4_HISTORICAL",
        "research_only": True, "eligible": False, "play_authority": False,
        "market_test": "NOT_ADMITTED",
        "close_status": "NOT_CERTIFIED_ACTUAL_FIRST_PLAY",
        "independent_fixture_verified": False,
        "independent_market_mapping_verified": False,
        "actual_start_bound": False,
        "admission_sha256": _canon(material),
        **material,
    }


def fetch_single_fixture_history(fixture_id: str, bookmaker: str,
                                 *, secret: str) -> Mapping[str, Any]:
    """Single credentialed historical request. Always sanitize errors."""
    _safe_id(fixture_id, "FIXTURE")
    if not isinstance(bookmaker, str) or not SAFE_BOOK.fullmatch(bookmaker):
        raise OddsPapiCandidateError("BOOKMAKER_SLUG_REQUIRED")
    if not secret:
        raise OddsPapiCandidateError("BLOCKED_NO_ODDSPAPI_KEY")
    # Provider requires apiKey as QUERY param. URL/exception never logged.
    url = BASE + "?" + urlencode({
        "fixtureId": fixture_id, "bookmakers": bookmaker, "apiKey": secret})
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SportsEdge-OddsPapi-Historical-Admission/1.0"})
    try:
        with urlopen(req, timeout=30) as res:
            raw = res.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        code = int(exc.code)
        if code in (401, 403):
            raise OddsPapiCandidateError(
                "BLOCKED_ODDSPAPI_CREDENTIAL_UNAUTHORIZED") from None
        if code == 429:
            raise OddsPapiCandidateError(
                "BLOCKED_ODDSPAPI_PROVIDER_COOLDOWN") from None
        raise OddsPapiCandidateError("BLOCKED_ODDSPAPI_HTTP_ERROR") from None
    except (URLError, TimeoutError):
        raise OddsPapiCandidateError("BLOCKED_ODDSPAPI_NETWORK_ERROR") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise OddsPapiCandidateError("BLOCKED_ODDSPAPI_PAYLOAD_TOO_LARGE")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise OddsPapiCandidateError("BLOCKED_ODDSPAPI_INVALID_JSON") from None
    if not isinstance(payload, Mapping):
        raise OddsPapiCandidateError("BLOCKED_ODDSPAPI_RESPONSE_OBJECT_REQUIRED")
    return payload


def _load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as reader:
        return json.load(reader)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(
        "OddsPapi 2026+ historical structural candidate screen, research only."))
    p.add_argument("--fixture-anchor-json", required=True)
    p.add_argument("--market-map-json", required=True)
    p.add_argument("--response-json", help="offline-only provider envelope")
    p.add_argument("--output-json", help="only sanitized candidate record")
    args = p.parse_args(argv)
    try:
        anchor = _load(args.fixture_anchor_json)
        mapping = _load(args.market_map_json)
        fixture, _ = _validate_anchor(anchor)
        book, _, _ = _validate_mapping(mapping, fixture)
        if args.response_json:
            payload = _load(args.response_json)
        else:
            payload = fetch_single_fixture_history(
                fixture, book, secret=os.getenv(SECRET, "").strip())
        result = inspect_historical_payload(payload, anchor, mapping)
        if args.output_json:
            dest = Path(args.output_json)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
            tmp.replace(dest)
        print(json.dumps({
            "status": result["status"], "research_only": True,
            "market_test": "NOT_ADMITTED",
            "provider": "ODDSPAPI_V4_HISTORICAL",
            "admission_sha256": result["admission_sha256"],
            "post_start_entries_ignored": result["post_start_entries_ignored"],
        }, sort_keys=True))
        return 0
    except OddsPapiCandidateError as exc:
        print(json.dumps({
            "status": str(exc), "provider": "ODDSPAPI_V4_HISTORICAL",
            "research_only": True, "eligible": False,
            "market_test": "NOT_ADMITTED",
        }, sort_keys=True))
        return 78
    except (OSError, ValueError, TypeError):
        print(json.dumps({
            "status": "BLOCKED_INVALID_LOCAL_EVIDENCE",
            "research_only": True, "eligible": False,
            "market_test": "NOT_ADMITTED",
        }, sort_keys=True))
        return 79


if __name__ == "__main__":
    raise SystemExit(main())
