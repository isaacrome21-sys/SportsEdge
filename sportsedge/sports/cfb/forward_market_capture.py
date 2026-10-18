"""Bounded forward-only CFB market capture planning and snapshot validation.

This module decides whether a paid current-market snapshot is due from a free
scoreboard feed.  It creates no Model_P, paired market evidence, promotion,
eligibility, staking, Truth Gate, or OFFICIAL authority.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

DECISION_MIN_LEAD_MINUTES = 45.0
DECISION_MAX_LEAD_MINUTES = 120.0
CLOSE_MIN_LEAD_MINUTES = 2.0
CLOSE_MAX_LEAD_MINUTES = 20.0


class CFBForwardMarketError(ValueError):
    pass


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CFBForwardMarketError(f"CFB_FORWARD_MARKET_TIMESTAMP_INVALID:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CFBForwardMarketError(f"CFB_FORWARD_MARKET_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed


def _event_rows(scoreboards: Iterable[Mapping[str, Any]]) -> Iterable[tuple[str, datetime]]:
    seen: set[str] = set()
    for scoreboard in scoreboards:
        events = scoreboard.get("events")
        if not isinstance(events, list):
            raise CFBForwardMarketError("CFB_SCOREBOARD_EVENTS_LIST_REQUIRED")
        for event in events:
            if not isinstance(event, Mapping):
                continue
            event_id = str(event.get("id") or "").strip()
            if not event_id or event_id in seen:
                continue
            status = event.get("status")
            if isinstance(status, Mapping):
                status_type = status.get("type")
                if isinstance(status_type, Mapping) and status_type.get("completed") is True:
                    continue
            start = _ts(event.get("date"), "event.date")
            seen.add(event_id)
            yield event_id, start


def plan_capture(scoreboards: Iterable[Mapping[str, Any]], *, now: str | datetime) -> dict[str, Any]:
    now_dt = _ts(now, "now") if not isinstance(now, datetime) else now
    if now_dt.tzinfo is None or now_dt.utcoffset() is None:
        raise CFBForwardMarketError("CFB_FORWARD_MARKET_TIMESTAMP_TZ_REQUIRED:now")
    decision_due: list[dict[str, Any]] = []
    close_due: list[dict[str, Any]] = []
    upcoming = 0
    for event_id, start in _event_rows(scoreboards):
        lead = (start - now_dt).total_seconds() / 60.0
        if lead <= 0:
            continue
        upcoming += 1
        row = {"scoreboard_event_id": event_id, "kickoff_utc": start.isoformat(), "lead_minutes": lead}
        if DECISION_MIN_LEAD_MINUTES <= lead <= DECISION_MAX_LEAD_MINUTES:
            decision_due.append(row)
        if CLOSE_MIN_LEAD_MINUTES <= lead <= CLOSE_MAX_LEAD_MINUTES:
            close_due.append(row)
    return {
        "contract": "SPORTSEDGE_CFB_FORWARD_MARKET_CAPTURE_PLAN_V1",
        "capture_due": bool(decision_due or close_due),
        "decision_due": decision_due,
        "close_due": close_due,
        "upcoming_event_count": upcoming,
        "decision_window_minutes": [DECISION_MAX_LEAD_MINUTES, DECISION_MIN_LEAD_MINUTES],
        "close_window_minutes": [CLOSE_MAX_LEAD_MINUTES, CLOSE_MIN_LEAD_MINUTES],
        "promotion_authority": False,
        "model_p_created": False,
        "eligibility_changed": False,
    }


def validate_draftkings_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise CFBForwardMarketError("CFB_FORWARD_MARKET_SNAPSHOT_LIST_REQUIRED")
    valid_events = 0
    dk_events = 0
    market_rows = 0
    for event in payload:
        if not isinstance(event, Mapping):
            raise CFBForwardMarketError("CFB_FORWARD_MARKET_EVENT_MAPPING_REQUIRED")
        event_id = str(event.get("id") or "").strip()
        commence = event.get("commence_time")
        if not event_id or not commence:
            raise CFBForwardMarketError("CFB_FORWARD_MARKET_EVENT_ID_OR_START_MISSING")
        _ts(commence, "commence_time")
        valid_events += 1
        books = event.get("bookmakers")
        if books is None:
            continue
        if not isinstance(books, list):
            raise CFBForwardMarketError("CFB_FORWARD_MARKET_BOOKMAKERS_LIST_REQUIRED")
        for book in books:
            if not isinstance(book, Mapping) or str(book.get("key") or "").lower() != "draftkings":
                continue
            dk_events += 1
            markets = book.get("markets")
            if not isinstance(markets, list):
                raise CFBForwardMarketError("CFB_FORWARD_MARKET_MARKETS_LIST_REQUIRED")
            for market in markets:
                if not isinstance(market, Mapping):
                    continue
                key = str(market.get("key") or "")
                if key not in {"h2h", "spreads", "totals"}:
                    continue
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list) or len(outcomes) < 2:
                    raise CFBForwardMarketError(f"CFB_FORWARD_MARKET_TWO_SIDED_OUTCOMES_REQUIRED:{key}")
                market_rows += 1
    return {
        "event_count": valid_events,
        "draftkings_event_count": dk_events,
        "two_sided_market_count": market_rows,
        "snapshot_usable": valid_events > 0 and dk_events > 0 and market_rows > 0,
        "promotion_authority": False,
        "paired_market_evidence": False,
    }
