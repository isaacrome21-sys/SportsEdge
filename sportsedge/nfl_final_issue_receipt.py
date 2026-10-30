"""Prepare a game-specific NFL lines issue from an archived direct-DK FINAL.

Pure formatter: no GitHub writes, no CLV counting, no implied quote authenticity.
The caller must supply genuine raw bytes and an independently obtained wall clock.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sportsedge.nfl_direct_capture_source import DirectCaptureError, game_rows_direct


class FinalIssueRouteError(ValueError):
    """An issue must not be edited from this receipt."""


_EVENT_TAG = re.compile(r"<!--\s*DK\s+event\s*:\s*(\d+)\b", re.IGNORECASE)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SOURCE = "DRAFTKINGS_DIRECT_WEB_V1"


def _utc(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FinalIssueRouteError("ROUTE_TIME_INVALID") from exc
    else:
        raise FinalIssueRouteError("ROUTE_TIME_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FinalIssueRouteError("ROUTE_TIME_NAIVE")
    return parsed.astimezone(timezone.utc)


def _nickname(team: object) -> str:
    words = re.findall(r"[a-z0-9]+", str(team or "").casefold())
    return words[-1] if words else ""


def _price(value: object) -> int:
    if type(value) is not int or -100 < value < 100:
        raise FinalIssueRouteError("ROUTE_PRICE_INVALID")
    return value


def _point(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FinalIssueRouteError("ROUTE_LINE_INVALID")
    number = float(value)
    if not math.isfinite(number):
        raise FinalIssueRouteError("ROUTE_LINE_INVALID")
    return number


def _line_text(value: float, *, signed: bool) -> str:
    return f"{value:+g}" if signed and value > 0 else f"{value:g}"


def _price_text(value: int) -> str:
    return f"{value:+d}" if value > 0 else str(value)


def format_final_issue(
    record: Mapping[str, object],
    raw_bytes: bytes,
    existing_issue_body: str,
    *,
    now: datetime,
) -> str:
    """Return replacement lines body only if all FINAL/identity gates pass.

    No permission to edit an issue is implied by successfully formatting it.
    The existing issue must carry exactly one DK event tag; no title-only match.
    Old ML/prop lines are deliberately NOT copied into a FINAL spread/total body.
    """
    if (not isinstance(record, Mapping)
            or record.get("capture_kind") != "FINAL"
            or record.get("book") != "draftkings"
            or record.get("source_class") != _SOURCE
            or record.get("no_backfill") is not True
            or record.get("promotion_authority") is not False):
        raise FinalIssueRouteError("ROUTE_SOURCE_NOT_FINAL_DIRECT")
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise FinalIssueRouteError("ROUTE_RAW_REQUIRED")
    transport = record.get("transport")
    schedule = record.get("schedule")
    if (not isinstance(transport, Mapping) or not isinstance(schedule, Mapping)
            or schedule.get("matching_semantics") != "KICKOFF_UTC_MULTIPLICITY"
            or not schedule.get("sha256") or not record.get("hashes")):
        raise FinalIssueRouteError("ROUTE_RECEIPT_PROVENANCE_MISSING")
    digest = transport.get("raw_sha256")
    raw_path = transport.get("raw_relative_path")
    uri = transport.get("source_uri")
    if (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
            or hashlib.sha256(raw_bytes).hexdigest() != digest
            or not isinstance(raw_path, str)
            or raw_path != f"raw/draftkings-direct/{digest}.json"):
        raise FinalIssueRouteError("ROUTE_RAW_DIGEST_MISMATCH")
    hostname = urlsplit(str(uri or "")).hostname
    if hostname != "sportsbook-nash.draftkings.com":
        raise FinalIssueRouteError("ROUTE_SOURCE_URI_UNVERIFIED")

    lines = str(existing_issue_body or "").splitlines()
    if not lines or " @ " not in lines[0]:
        raise FinalIssueRouteError("ROUTE_GAME_HEADER_INVALID")
    header = lines[0].strip()
    if header.count(" @ ") != 1:
        raise FinalIssueRouteError("ROUTE_GAME_HEADER_INVALID")
    away, home = (part.strip() for part in header.split(" @ ", 1))
    tags = _EVENT_TAG.findall(existing_issue_body)
    if len(tags) != 1:
        raise FinalIssueRouteError("ROUTE_EVENT_TAG_MISSING_OR_DUPLICATE")
    event_id = tags[0]
    games = record.get("games")
    if not isinstance(games, list):
        raise FinalIssueRouteError("ROUTE_GAMES_MISSING")
    matches = [g for g in games if isinstance(g, Mapping) and str(g.get("event_id")) == event_id]
    if len(matches) != 1:
        raise FinalIssueRouteError("ROUTE_EVENT_NOT_UNIQUE")
    game = matches[0]
    if (not _nickname(away) or _nickname(away) != _nickname(game.get("away_team"))
            or not _nickname(home) or _nickname(home) != _nickname(game.get("home_team"))
            or _nickname(away) == _nickname(home)):
        raise FinalIssueRouteError("ROUTE_GAME_IDENTITY_MISMATCH")
    if game.get("source_class") != _SOURCE or game.get("book") != "draftkings":
        raise FinalIssueRouteError("ROUTE_GAME_SOURCE_MISMATCH")

    received = _utc(record.get("retrieved_at_utc"))
    if _utc(game.get("observed_at_utc")) != received:
        raise FinalIssueRouteError("ROUTE_RECEIPT_TIME_MISMATCH")
    kickoff = _utc(game.get("commence_time"))
    delivered = _utc(now)
    # Frozen NFL FINAL contract: opening at -30m, closing at -15m.
    start = kickoff - timedelta(minutes=30)
    end = start + timedelta(minutes=15)
    if not start <= received < end:
        raise FinalIssueRouteError("ROUTE_FINAL_RECEIPT_OUTSIDE_WINDOW")
    if not received <= delivered < kickoff or not 0 <= (delivered - received).total_seconds() <= 180:
        raise FinalIssueRouteError("ROUTE_DELIVERY_STALE_OR_POSTSTART")

    spread = game.get("spread")
    total = game.get("total")
    if (not isinstance(spread, Mapping) or not isinstance(total, Mapping)
            or spread.get("status") != "OK" or total.get("status") != "OK"):
        raise FinalIssueRouteError("ROUTE_TWO_SIDED_MARKETS_MISSING")
    away_point = _point(spread.get("away_point"))
    home_point = _point(spread.get("home_point"))
    total_point = _point(total.get("point"))
    if not math.isclose(away_point, -home_point, rel_tol=0, abs_tol=1e-9) or total_point <= 0:
        raise FinalIssueRouteError("ROUTE_MARKET_POINTS_INVALID")
    away_price, home_price = _price(spread.get("away_price")), _price(spread.get("home_price"))
    over_price, under_price = _price(total.get("over_price")), _price(total.get("under_price"))
    # A matching raw SHA alone does not bind the market prices to the raw board.
    # Re-normalize the archived response using the same direct-source parser and
    # refuse a record whose event, start, teams or quote differs at all.
    try:
        payload = json.loads(
            raw_bytes,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
        if not isinstance(payload, Mapping):
            raise ValueError("RAW_ROOT_INVALID")
        events = payload.get("events")
        if not isinstance(events, list) or sum(
            isinstance(event, Mapping) and str(event.get("id")) == event_id
            for event in events
        ) != 1:
            raise ValueError("RAW_EVENT_NOT_UNIQUE")
        direct_rows = game_rows_direct(
            {
                "sport_key": "americanfootball_nfl",
                "source_uri": str(uri),
                "raw_bytes": raw_bytes,
                "raw_payload": payload,
                "observed_at_utc": received.isoformat().replace("+00:00", "Z"),
            },
            week_of=lambda _kickoff: 0,
        )
    except (ValueError, TypeError, KeyError, OverflowError, DirectCaptureError) as exc:
        raise FinalIssueRouteError("ROUTE_RAW_MARKET_PARSE_BLOCKED") from exc
    raw_matches = [row for row in direct_rows if str(row.get("event_id")) == event_id]
    if len(raw_matches) != 1:
        raise FinalIssueRouteError("ROUTE_RAW_EVENT_MARKETS_NOT_UNIQUE")
    direct_game = raw_matches[0]
    if (
        direct_game.get("away_team") != game.get("away_team")
        or direct_game.get("home_team") != game.get("home_team")
        or _utc(direct_game.get("commence_time")) != kickoff
        or direct_game.get("spread", {}).get("status") != "OK"
        or direct_game.get("total", {}).get("status") != "OK"
    ):
        raise FinalIssueRouteError("ROUTE_RAW_IDENTITY_OR_MARKET_MISMATCH")
    derived_spread = direct_game["spread"]
    derived_total = direct_game["total"]
    if (
        _point(derived_spread.get("away_point")) != away_point
        or _point(derived_spread.get("home_point")) != home_point
        or _price(derived_spread.get("away_price")) != away_price
        or _price(derived_spread.get("home_price")) != home_price
        or _point(derived_total.get("point")) != total_point
        or _price(derived_total.get("over_price")) != over_price
        or _price(derived_total.get("under_price")) != under_price
    ):
        raise FinalIssueRouteError("ROUTE_RAW_QUOTE_MISMATCH")

    captured = received.isoformat().replace("+00:00", "Z")
    return "\n".join([
        header,
        f"Captured: {captured}",
        f"<!-- DK event: {event_id}; FINAL raw SHA256: {digest} -->",
        f"Spread {_line_text(away_point, signed=True)} {_price_text(away_price)} {_price_text(home_price)}",
        f"Total {_line_text(total_point, signed=False)} {_price_text(over_price)} {_price_text(under_price)}",
        "",
    ])
