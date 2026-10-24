"""Bind already-captured, paired DraftKings game quotes to canonical RUN IT.

No sportsbook requests, no bookmaker-derived Model_P, no invented opposite
side. This is an adapter over the existing metered, quota-guarded capture.
Unsupported markets and expired snapshots are accounted for explicitly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

from scripts.collect_auto_dk_four_sports import IL_TEAMS
from sportsedge.quote_freshness import MAX_QUOTE_AGE_SECONDS

SUPPORTED_SPORTS = frozenset({"MLB", "NBA", "CFB", "NFL"})
MARKET_TYPES = {"h2h": "ML", "spreads": "SPREAD", "totals": "TOTAL"}


def _utc(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError, OverflowError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _valid_price(value) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and (value <= -100 or value >= 100))


def _line(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not isfinite(value) or abs(value) > 10000:
        return None
    return float(value)


def bind_capture(snapshot: Mapping[str, Any], *, now: datetime):
    """Return (canonical two-sided quote rows, explicit refusal receipts).

    Only the independently captured DK quotes move across this seam.
    The `estimate_p: null` book-board placeholder is NEVER propagated.
    """
    current = _utc(now)
    if current is None:
        raise ValueError("DK_CANONICAL_NOW_TIMEZONE_REQUIRED")
    sport = str(snapshot.get("sport") or "").upper()
    if sport not in SUPPORTED_SPORTS:
        raise ValueError("DK_CANONICAL_UNSUPPORTED_SPORT")
    if snapshot.get("source") != "THE_ODDS_API_V4":
        raise ValueError("DK_CANONICAL_CAPTURE_PROVENANCE_INVALID")
    if snapshot.get("status") != "READY":
        return [], [{"sport": sport, "reason": str(snapshot.get("reason") or
                       snapshot.get("status") or "CAPTURE_UNAVAILABLE")}]
    captured = _utc(snapshot.get("captured_at_utc"))
    if captured is None or not 0 <= (current - captured).total_seconds() <= MAX_QUOTE_AGE_SECONDS:
        return [], [{"sport": sport, "reason": "SNAPSHOT_CAPTURE_EXPIRED_OR_INVALID"}]
    games = snapshot.get("games")
    if not isinstance(games, list):
        raise ValueError("DK_CANONICAL_GAMES_NOT_LIST")

    lines, refusals, identities = [], [], set()
    for position, game in enumerate(games):
        if not isinstance(game, Mapping):
            refusals.append({"sport": sport, "game_index": position,
                             "reason": "GAME_NOT_OBJECT"})
            continue
        event = str(game.get("provider_event_id") or "").strip()
        away, home = game.get("away"), game.get("home")
        kickoff = _utc(game.get("commence_time"))
        if (not event or not isinstance(away, str) or not away.strip()
                or not isinstance(home, str) or not home.strip() or away == home
                or kickoff is None or kickoff <= current):
            refusals.append({"sport": sport, "game_index": position,
                             "reason": "EVENT_IDENTITY_OR_FUTURE_KICKOFF_INVALID"})
            continue
        if event in identities:
            refusals.append({"sport": sport, "game_index": position,
                             "reason": "DUPLICATE_PROVIDER_EVENT_ID"})
            continue
        identities.add(event)
        if sport == "CFB" and any(t.lower().startswith(IL_TEAMS)
                                   for t in (away, home)):
            refusals.append({"sport": sport, "game_index": position,
                             "reason": "ILLINOIS_COLLEGE_EXCLUDED"})
            continue
        markets = game.get("markets")
        if not isinstance(markets, Mapping):
            refusals.append({"sport": sport, "game_index": position,
                             "reason": "PAIRED_MARKET_OBJECT_MISSING"})
            continue
        for source_market, market in markets.items():
            if source_market not in MARKET_TYPES:
                refusals.append({"sport": sport, "game_index": position,
                                 "market": str(source_market),
                                 "reason": "MARKET_NOT_SUPPORTED_BY_CAPTURE"})
                continue
            if not isinstance(market, Mapping) or market.get("book") != "draftkings":
                refusals.append({"sport": sport, "game_index": position,
                                 "market": source_market,
                                 "reason": "BOOK_IDENTITY_OR_MARKET_MISSING"})
                continue
            observed = _utc(market.get("observed_at"))
            if (observed is None or not 0 <= (current - observed).total_seconds()
                    <= MAX_QUOTE_AGE_SECONDS):
                refusals.append({"sport": sport, "game_index": position,
                                 "market": source_market,
                                 "reason": "MARKET_QUOTE_EXPIRED_OR_FUTURE"})
                continue
            if source_market == "h2h":
                sides = (("AWAY", None, market.get("away")),
                         ("HOME", None, market.get("home")))
            elif source_market == "spreads":
                point = _line(market.get("line"))
                sides = (("AWAY", point, market.get("away")),
                         ("HOME", -point if point is not None else None,
                          market.get("home")))
            else:
                point = _line(market.get("line"))
                sides = (("OVER", point, market.get("over")),
                         ("UNDER", point, market.get("under")))
            if (any(not _valid_price(price) for _, _, price in sides)
                    or (source_market != "h2h" and
                        any(point is None for _, point, _ in sides))):
                refusals.append({"sport": sport, "game_index": position,
                                 "market": source_market,
                                 "reason": "PAIR_PRICE_OR_THRESHOLD_INVALID"})
                continue
            for side, threshold, odds in sides:
                lines.append({
                    "sport": sport, "away": away, "home": home,
                    "kickoff": kickoff.isoformat(),
                    "market": MARKET_TYPES[source_market],
                    "side": side, "line": threshold,
                    "odds": odds, "book": "draftkings",
                    "quote_captured_at": observed.isoformat(),
                    "quote_timestamp_source": "PROVIDER_LAST_UPDATE",
                    "capture_event_id": event,
                })
    return lines, refusals
