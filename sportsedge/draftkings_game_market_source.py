"""Direct DraftKings pregame game-market transport for prospective archive use.

Original SportsEdge adapter informed by publicly documented DraftKings sportscontent
usage patterns. It creates no Model_P or evidence authority. Consumers must preserve
raw response bytes and independently enforce PIT/admission contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

DK_ROOT = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1"
LEAGUE_IDS = {
    "americanfootball_nfl": 88808,
    "americanfootball_ncaaf": 87637,
    "baseball_mlb": 84240,
}
VERIFIED_GAME_LINE_CATEGORY_IDS = {
    "americanfootball_nfl": 492,
    "baseball_mlb": 493,
}

class DraftKingsGameMarketError(RuntimeError):
    pass

@dataclass(frozen=True)
class RawDraftKingsBoard:
    sport_key: str
    source_uri: str
    raw: bytes
    received_at: datetime
    payload: Mapping[str, Any]


def game_line_category_id(sport_key: str) -> int:
    if sport_key not in LEAGUE_IDS:
        raise DraftKingsGameMarketError("DK_GAME_SPORT_UNSUPPORTED")
    category_id = VERIFIED_GAME_LINE_CATEGORY_IDS.get(sport_key)
    if category_id is None:
        raise DraftKingsGameMarketError("DK_GAME_CATEGORY_UNVERIFIED")
    return int(category_id)


def board_url(sport_key: str) -> str:
    league_id = LEAGUE_IDS.get(sport_key)
    if league_id is None:
        raise DraftKingsGameMarketError("DK_GAME_SPORT_UNSUPPORTED")
    return f"{DK_ROOT}/leagues/{league_id}/categories/{game_line_category_id(sport_key)}"


def _open(url: str, timeout: int = 20):
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 SportsEdge-DK-Market-Archive/1",
        "Referer": "https://sportsbook.draftkings.com/",
        "Origin": "https://sportsbook.draftkings.com",
    })
    return urlopen(req, timeout=timeout)


def fetch_board(sport_key: str, *, opener: Callable[..., Any] = _open,
                clock: Callable[[], datetime] | None = None) -> RawDraftKingsBoard:
    uri = board_url(sport_key)
    try:
        with opener(uri, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise DraftKingsGameMarketError("DK_GAME_FETCH_FAILED") from exc
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise DraftKingsGameMarketError("DK_GAME_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, Mapping):
        raise DraftKingsGameMarketError("DK_GAME_RESPONSE_SHAPE_INVALID")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise DraftKingsGameMarketError("DK_GAME_RECEIPT_TIME_INVALID")
    return RawDraftKingsBoard(sport_key, uri, raw, now.astimezone(timezone.utc), payload)


def _american(selection: Mapping[str, Any]) -> int:
    display = selection.get("displayOdds")
    value: Any = display.get("american") if isinstance(display, Mapping) else display
    if value is None:
        value = selection.get("oddsAmerican") or selection.get("americanOdds")
    text = str(value or "").strip().replace("−", "-").replace("+", "")
    try:
        return int(text)
    except Exception as exc:
        raise DraftKingsGameMarketError("DK_GAME_ODDS_INVALID") from exc


def _event_teams(event: Mapping[str, Any]) -> tuple[str, str]:
    name = str(event.get("name") or "").strip()
    if " @ " not in name:
        raise DraftKingsGameMarketError("DK_GAME_EVENT_TEAMS_INVALID")
    away, home = (part.strip() for part in name.split(" @ ", 1))
    if not away or not home:
        raise DraftKingsGameMarketError("DK_GAME_EVENT_TEAMS_INVALID")
    return away, home


def _parse_start(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception as exc:
        raise DraftKingsGameMarketError("DK_GAME_START_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DraftKingsGameMarketError("DK_GAME_START_INVALID")
    return dt.astimezone(timezone.utc)


def normalize_board(board: RawDraftKingsBoard) -> list[dict[str, Any]]:
    payload = board.payload
    events = {str(e.get("id")): e for e in payload.get("events", []) if isinstance(e, Mapping) and e.get("id") is not None}
    markets = [m for m in payload.get("markets", []) if isinstance(m, Mapping)]
    selections = [s for s in payload.get("selections", []) if isinstance(s, Mapping)]
    by_market: dict[str, list[Mapping[str, Any]]] = {}
    for selection in selections:
        mid = str(selection.get("marketId") or "")
        if mid:
            by_market.setdefault(mid, []).append(selection)

    rows: list[dict[str, Any]] = []
    for market in markets:
        name = str(market.get("name") or "").strip()
        event_id = str(market.get("eventId") or "")
        event = events.get(event_id)
        if event is None:
            continue
        canonical = None
        if name == "Moneyline": canonical = "h2h"
        elif name in {"Spread", "Run Line"}: canonical = "spreads"
        elif name == "Total": canonical = "totals"
        if canonical is None:
            continue
        try:
            away, home = _event_teams(event)
            start = _parse_start(event.get("startEventDate"))
        except DraftKingsGameMarketError:
            continue
        sels = by_market.get(str(market.get("id") or ""), [])
        normalized: list[dict[str, Any]] = []
        for selection in sels:
            label = str(selection.get("label") or "").strip()
            try:
                price = _american(selection)
            except DraftKingsGameMarketError:
                continue
            point = selection.get("points")
            outcome = None
            if canonical == "totals":
                low = label.lower()
                if low.startswith("over"): outcome = "Over"
                elif low.startswith("under"): outcome = "Under"
            else:
                if home in label or label in home: outcome = home
                elif away in label or label in away: outcome = away
                else:
                    hm = home.split()[-1] in label if home.split() else False
                    am = away.split()[-1] in label if away.split() else False
                    if hm ^ am: outcome = home if hm else away
            if outcome is None:
                continue
            normalized.append({"outcome": outcome, "point": point, "price_american": price})
        outcomes = {r["outcome"] for r in normalized}
        expected = {home, away} if canonical != "totals" else {"Over", "Under"}
        if outcomes != expected or len(normalized) != 2:
            continue
        for item in normalized:
            rows.append({
                "provider": "DRAFTKINGS_DIRECT_WEB",
                "sportsbook": "draftkings",
                "sport_key": board.sport_key,
                "provider_event_id": event_id,
                "home_team": home,
                "away_team": away,
                "commence_time": start.isoformat().replace("+00:00", "Z"),
                "market": canonical,
                **item,
            })
    return rows
