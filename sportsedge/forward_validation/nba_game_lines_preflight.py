"""Offline NBA game-line prospective capture *preflight*, NOT an evaluator.

The 2026-10-20 NBA game-lines prereg is DRAFT and no candidate passed
its separate historical accuracy entry screen. Accordingly this module
cannot issue a prospective verdict or begin the clock, even if a caller
asserts a pass. It classifies only captured entry/close evidence as
defined by the draft's five missing-close reasons, and always reports
DRY_RUN_ONLY. A caller-supplied SHA is shape evidence, not a certified
independent fixture/market identity.

Does not alter forward_validation/core.py, live capture, the frozen
NBA player props clock, held NBA game-line models, or any registry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
import re
from typing import Any, Mapping, Sequence

VERSION = "NBA_GAME_LINES_EVIDENCE_PREFLIGHT_V1"
MARKETS = {"MONEYLINE": ("HOME", "AWAY"),
           "SPREAD": ("HOME", "AWAY"),
           "TOTAL": ("OVER", "UNDER")}
CLOSE_MAX_AGE_SECONDS = 3600
QUOTE_MAX_AGE_SECONDS = 180
PAIR_SPAN_MAX_SECONDS = 150
DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
ID = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
ENVELOPE_FIELDS = {"schema", "fixtures"}
FIXTURE_FIELDS = {"event_id", "event_start_utc", "fixture_source_sha256",
                  "market", "entry", "closes"}
CAPTURE_FIELDS = {"event_id", "market", "line", "capture_id",
                  "captured_at_utc", "bookmaker", "quotes"}
QUOTE_FIELDS = {"side", "american_odds", "quote_at_utc",
                "receipt_sha256"}


class GameLinePreflightError(ValueError):
    """Sanitized data refusal, never an invitation to backfill."""


def _id(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not ID.fullmatch(raw):
        raise GameLinePreflightError(f"{name}_IDENTITY_REQUIRED")
    return raw


def _sha(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not DIGEST.fullmatch(raw):
        raise GameLinePreflightError(f"{name}_HASH_REQUIRED")
    return raw.lower()


def _utc(raw: Any, name: str) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise GameLinePreflightError(f"{name}_TIMESTAMP_REQUIRED")
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GameLinePreflightError(f"{name}_TIMESTAMP_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise GameLinePreflightError(f"{name}_UTC_OFFSET_REQUIRED")
    return d.astimezone(timezone.utc)


def _line(raw: Any, market: str) -> float | None:
    if market == "MONEYLINE":
        if raw is not None:
            raise GameLinePreflightError("MONEYLINE_MUST_HAVE_NULL_LINE")
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise GameLinePreflightError("SPREAD_TOTAL_FINITE_LINE_REQUIRED")
    v = float(raw)
    if not isfinite(v) or abs(v) > 500 or v * 2 != round(v * 2):
        raise GameLinePreflightError("SPREAD_TOTAL_HALF_POINT_LINE_REQUIRED")
    return v


def _price(value: Any) -> int:
    if type(value) is not int or not (-10000 <= value <= 10000) or (
            -100 < value < 100):
        raise GameLinePreflightError("INVALID_AMERICAN_ODDS")
    return value


def _capture(raw: Any, *, event: str, market: str,
             start: datetime, entry: bool) -> dict:
    if not isinstance(raw, Mapping) or set(raw) != CAPTURE_FIELDS:
        raise GameLinePreflightError("CAPTURE_CONTRACT_MISMATCH")
    if raw.get("event_id") != event or raw.get("market") != market:
        raise GameLinePreflightError("CROSS_EVENT_OR_MARKET_CAPTURE")
    if raw.get("bookmaker") != "DraftKings":
        raise GameLinePreflightError("NOT_INDEPENDENT_DRAFTKINGS_CAPTURE")
    capture_id = _id(raw.get("capture_id"), "CAPTURE")
    time = _utc(raw.get("captured_at_utc"), "CAPTURE")
    line = _line(raw.get("line"), market)
    quotes = raw.get("quotes")
    if not isinstance(quotes, list) or not quotes:
        raise GameLinePreflightError("CAPTURE_QUOTES_REQUIRED")
    allowed = set(MARKETS[market])
    seen: dict[str, dict] = {}
    times: list[datetime] = []
    for q in quotes:
        if not isinstance(q, Mapping) or set(q) != QUOTE_FIELDS:
            raise GameLinePreflightError("QUOTE_CONTRACT_MISMATCH")
        side = q.get("side")
        if not isinstance(side, str) or side not in allowed or side in seen:
            raise GameLinePreflightError("DUPLICATE_OR_UNKNOWN_QUOTE_SIDE")
        value = _price(q.get("american_odds"))
        at = _utc(q.get("quote_at_utc"), "QUOTE")
        if at > time or (time - at).total_seconds() > QUOTE_MAX_AGE_SECONDS:
            raise GameLinePreflightError("QUOTE_AGE_OR_CHRONOLOGY_INVALID")
        times.append(at)
        seen[side] = {
            "side": side, "american_odds": value,
            "quote_at_utc": at.isoformat(),
            "receipt_sha256": _sha(q.get("receipt_sha256"), "QUOTE_RECEIPT"),
        }
    if (max(times) - min(times)).total_seconds() > PAIR_SPAN_MAX_SECONDS:
        raise GameLinePreflightError("CAPTURE_PAIR_SPAN_EXCEEDS_150S")
    if entry and set(seen) != allowed:
        raise GameLinePreflightError("ENTRY_REQUIRES_BOTH_REAL_SIDES")
    return {
        "capture_id": capture_id, "captured_at": time, "line": line,
        "present_sides": frozenset(seen),
        "pair_complete": set(seen) == allowed,
        "identity_hash": sha256(json.dumps({
            "event_id": event, "market": market, "line": line,
            "capture_id": capture_id,
            "captured_at_utc": time.isoformat(),
            "quotes": sorted(seen.values(), key=lambda x: x["side"]),
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def _classify_close(entry: dict, closes: list[dict],
                    start: datetime, market: str) -> tuple[str, str | None]:
    if not closes:
        return "CLV_MISSING", "NO_CLOSE_ROW"
    pre = [c for c in closes if c["captured_at"] < start]
    if not pre:
        return "CLV_MISSING", "CLOSE_NOT_PREKICKOFF"
    last_time = max(c["captured_at"] for c in pre)
    latest = [c for c in pre if c["captured_at"] == last_time]
    if len(latest) != 1:
        # Never pick a favorable conflicting capture arbitrarily.
        raise GameLinePreflightError("AMBIGUOUS_LAST_PRETIP_CAPTURE")
    close = latest[0]
    if (start - close["captured_at"]).total_seconds() > CLOSE_MAX_AGE_SECONDS:
        return "CLV_MISSING", "CLOSE_STALE"
    if market != "MONEYLINE" and close["line"] != entry["line"]:
        return "CLV_MISSING", "LINE_MOVED"
    if not close["pair_complete"]:
        reason = "LINE_MOVED" if market == "MONEYLINE" else "CLOSE_SINGLE_SIDED"
        return "CLV_MISSING", reason
    return "CLOSE_PAIR_FOUND_NOT_CERTIFIED", None


def audit_nba_game_line_capture_preflight(payload: Mapping[str, Any]) -> dict:
    """Offline eligibility *diagnostic* for raw captures. No scoring clock.

    Refuse arbitrary caller freeze flags or prior-pass claims by allowing
    only the schema+fixtures fields. Independently corroborated candidate,
    prereg freeze, actual-tip clock and bookmaker identity are NOT present;
    not even perfectly shaped captures can convert to real countable data.
    """
    if not isinstance(payload, Mapping) or set(payload) != ENVELOPE_FIELDS or (
            payload.get("schema") != VERSION):
        raise GameLinePreflightError("DRAFT_PREFLIGHT_SCHEMA_ONLY")
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise GameLinePreflightError("NONEMPTY_FIXTURE_RECORDS_REQUIRED")
    rows = []
    keys = set()
    counts = {"CLOSE_PAIR_FOUND_NOT_CERTIFIED": 0}
    for f in fixtures:
        if not isinstance(f, Mapping) or set(f) != FIXTURE_FIELDS:
            raise GameLinePreflightError("FIXTURE_CONTRACT_MISMATCH")
        event = _id(f.get("event_id"), "EVENT")
        market = f.get("market")
        if not isinstance(market, str) or market not in MARKETS:
            raise GameLinePreflightError("MARKET_OUT_OF_SCOPE")
        key = (event, market)
        if key in keys:
            raise GameLinePreflightError("DUPLICATE_EVENT_MARKET")
        keys.add(key)
        start = _utc(f.get("event_start_utc"), "EVENT_START")
        fixture_sha = _sha(f.get("fixture_source_sha256"), "FIXTURE")
        entry = _capture(f.get("entry"), event=event, market=market,
                         start=start, entry=True)
        close_list = f.get("closes")
        if not isinstance(close_list, list):
            raise GameLinePreflightError("CLOSE_LIST_REQUIRED")
        closes = [_capture(c, event=event, market=market, start=start,
                           entry=False) for c in close_list]
        if len(set(c["capture_id"] for c in closes)) != len(closes) or (
                entry["capture_id"] in {c["capture_id"] for c in closes}):
            raise GameLinePreflightError("DUPLICATE_CAPTURE_RECEIPT_ID")
        if entry["captured_at"] >= start:
            classification, reason = "ENTRY_NOT_PRE_EVENT", "ENTRY_NOT_PRE_EVENT"
        else:
            classification, reason = _classify_close(entry, closes, start, market)
        counts[classification if reason is None else reason] = (
            counts.get(classification if reason is None else reason, 0) + 1)
        rows.append({
            "event_market_hash12": sha256(
                f"{event}|{market}|{fixture_sha}".encode()).hexdigest()[:12],
            "market": market, "classification": classification,
            "missing_close_reason": reason,
            "entry_line": entry["line"],
            "entry_capture_sha256": entry["identity_hash"],
            "selected_close_certified": False,
            "source_fixture_independently_verified": False,
        })
    return {
        "status": "DRY_RUN_ONLY_PREREG_NOT_FROZEN",
        "version": VERSION,
        "clock_started": False,
        "historical_accuracy_screen_passed": False,
        "candidate_frozen": False,
        "market_test": "NOT_STARTED",
        "eligibility": False,
        "play_authority": False,
        "readiness_counts": dict(sorted(counts.items())),
        "diagnostic_rows": sorted(rows, key=lambda x: x["event_market_hash12"]),
        "countable_prospective_rows": 0,
        "verdict": "NO_VERDICT_DRAFT",
    }
