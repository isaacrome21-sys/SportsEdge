"""Poll-based live ingestion for SportsEdge research repricing.

FREE SOURCES ONLY -- no paid feeds, no scraping behind logins:
  - MLB: MLB StatsAPI (live feed + schedule)
  - NFL/CFB: ESPN public scoreboard API

Poll cadence and rate-limit behavior (documented, see docs/live_inplay.md):
  - LIVE_POLL_CADENCE_SECONDS = 30 per live event per provider.
  - LIVE_MAX_REQUESTS_PER_MINUTE = 40 per provider (conservative vs. the
    public endpoints; both tolerate far more, but research polling must not
    look like abuse).
  - HTTP 429 is a HARD STOP for that provider in the current task
    (LiveRateLimited is raised, no retry, no backoff loop) -- per the
    standing runtime policy a 429 ends provider work for the attempt.
  - Between sequential requests in a loop, a small spacing delay
    (LIVE_REQUEST_SPACING_SECONDS) keeps bursts down.

Freshness: every fetched snapshot carries observed_at (our retrieval time)
and source_as_of (the provider's own timestamp when present). The
repricing path treats any state older than
LIVE_STATE_STALENESS_THRESHOLD_SECONDS (60s) as STALE_LIVE_DATA.

All functions accept an injectable ``getter(url) -> parsed JSON`` so unit
tests never touch the network.
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .live_state import (
    LIVE_STATE_STALENESS_THRESHOLD_SECONDS,
    FootballGameState,
    LiveStateError,
    MLBGameState,
    parse_espn_football_event,
    parse_mlb_live_feed,
)


LIVE_POLL_CADENCE_SECONDS = 30
LIVE_MAX_REQUESTS_PER_MINUTE = 40
LIVE_REQUEST_SPACING_SECONDS = 0.25
LIVE_HTTP_TIMEOUT_SECONDS = 15

MLB_LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
MLB_SCHEDULE_URL = ("https://statsapi.mlb.com/api/v1/schedule"
                    "?sportId=1&startDate={start}&endDate={end}&hydrate=team,linescore")
ESPN_SCOREBOARD_URLS = {
    "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "CFB": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
}

JsonGetter = Callable[[str], Any]


class LiveRateLimited(RuntimeError):
    """HTTP 429 from a free provider: hard stop, no retry in this attempt."""


class LiveFetchError(RuntimeError):
    """Non-429 fetch failure with the provider and URL attached."""


def _default_get_json(url: str) -> Any:
    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SportsEdge-free-research/1.0",
    })
    try:
        with urlopen(request, timeout=LIVE_HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise LiveRateLimited(f"429 from {url}") from exc
        raise LiveFetchError(f"HTTP {exc.code} from {url}") from exc
    except (OSError, TimeoutError, ValueError) as exc:
        raise LiveFetchError(f"fetch failed for {url}: {type(exc).__name__}") from exc


class PollBudget:
    """Per-provider request budget: max N requests per rolling minute."""

    def __init__(self, max_per_minute: int = LIVE_MAX_REQUESTS_PER_MINUTE,
                 spacing_seconds: float = LIVE_REQUEST_SPACING_SECONDS):
        if max_per_minute <= 0:
            raise ValueError("max_per_minute must be > 0")
        self.max_per_minute = int(max_per_minute)
        self.spacing_seconds = float(spacing_seconds)
        self._times: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._times and now - self._times[0] >= 60.0:
            self._times.popleft()

    def acquire(self) -> None:
        """Block until a request slot is available. Never exceeds the cap."""
        while True:
            now = time.monotonic()
            self._prune(now)
            if len(self._times) < self.max_per_minute:
                if self._times and now - self._times[-1] < self.spacing_seconds:
                    time.sleep(self.spacing_seconds - (now - self._times[-1]))
                    continue
                self._times.append(time.monotonic())
                return
            oldest = self._times[0]
            time.sleep(max(0.0, 60.0 - (time.monotonic() - oldest) + 0.01))

    @property
    def used_in_window(self) -> int:
        self._prune(time.monotonic())
        return len(self._times)


class LivePoller:
    """Poll-based live state ingestion with provenance receipts.

    Typical use is one poll per research-card request ("he sends live lines,
    gets a research card back"); ``poll_due`` supports unattended loops that
    respect LIVE_POLL_CADENCE_SECONDS per event.
    """

    def __init__(self, *, getter: JsonGetter | None = None,
                 budget: PollBudget | None = None,
                 now: Callable[[], datetime] | None = None):
        self._get_json = getter or _default_get_json
        self._budget = budget or PollBudget()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._last_poll: dict[str, float] = {}

    # -- plumbing ------------------------------------------------------
    def _fetch(self, url: str) -> tuple[Any, dict[str, Any]]:
        retrieved_at = self._now()
        self._budget.acquire()
        try:
            data = self._get_json(url)
        except LiveRateLimited:
            raise
        except LiveFetchError:
            raise
        except Exception as exc:  # injected getters may raise anything
            raise LiveFetchError(f"getter failed for {url}: {type(exc).__name__}") from exc
        receipt = {
            "url": url,
            "retrieved_at_utc": retrieved_at.isoformat(),
            "status": "FETCHED",
        }
        return data, receipt

    def poll_due(self, key: str, *, cadence_seconds: int = LIVE_POLL_CADENCE_SECONDS) -> bool:
        last = self._last_poll.get(key)
        now = time.monotonic()
        if last is None or now - last >= cadence_seconds:
            self._last_poll[key] = now
            return True
        return False

    # -- MLB -----------------------------------------------------------
    def fetch_mlb_state(self, game_pk: int) -> tuple[MLBGameState, dict[str, Any]]:
        if isinstance(game_pk, bool) or int(game_pk) <= 0:
            raise LiveStateError("GAME_PK_INVALID")
        url = MLB_LIVE_FEED_URL.format(game_pk=int(game_pk))
        data, receipt = self._fetch(url)
        retrieved_at = datetime.fromisoformat(receipt["retrieved_at_utc"])
        try:
            state = parse_mlb_live_feed(data, retrieved_at=retrieved_at,
                                        game_pk=int(game_pk))
        except LiveStateError as exc:
            receipt["status"] = "PARSE_FAILED"
            receipt["reason"] = str(exc)
            raise
        receipt["source_as_of_utc"] = state.source_as_of.isoformat()
        receipt["game_status"] = state.status
        return state, receipt

    def discover_mlb_game(self, *, home: str, away: str,
                          date: str) -> tuple[int, dict[str, Any]]:
        """Resolve gamePk for a team pair on a YYYY-MM-DD date via schedule."""
        url = MLB_SCHEDULE_URL.format(start=date, end=date)
        data, receipt = self._fetch(url)
        for day in (data or {}).get("dates") or []:
            for game in day.get("games") or []:
                teams = game.get("teams") or {}
                h = ((teams.get("home") or {}).get("team") or {}).get("name", "")
                a = ((teams.get("away") or {}).get("team") or {}).get("name", "")
                if _name_match(h, home) and _name_match(a, away):
                    receipt["resolved_game_pk"] = game.get("gamePk")
                    return int(game["gamePk"]), receipt
        raise LiveStateError("LIVE_EVENT_NOT_FOUND")

    # -- NFL / CFB -----------------------------------------------------
    def fetch_football_state(self, sport: str, *,
                             event_id: str | None = None,
                             home: str | None = None,
                             away: str | None = None
                             ) -> tuple[FootballGameState, dict[str, Any]]:
        sport = str(sport).upper()
        if sport not in ESPN_SCOREBOARD_URLS:
            raise LiveStateError("SPORT_INVALID")
        url = ESPN_SCOREBOARD_URLS[sport]
        data, receipt = self._fetch(url)
        retrieved_at = datetime.fromisoformat(receipt["retrieved_at_utc"])
        events = (data or {}).get("events") or []
        match = None
        for item in events:
            if event_id and str(item.get("id")) == str(event_id):
                match = item
                break
        if match is None and home and away:
            for item in events:
                names = _competitor_names(item)
                if _name_match(names[0], home) and _name_match(names[1], away):
                    match = item
                    break
        if match is None:
            receipt["status"] = "EVENT_NOT_FOUND"
            raise LiveStateError("LIVE_EVENT_NOT_FOUND")
        try:
            state = parse_espn_football_event(match, sport=sport,
                                              retrieved_at=retrieved_at)
        except LiveStateError as exc:
            receipt["status"] = "PARSE_FAILED"
            receipt["reason"] = str(exc)
            raise
        receipt["source_as_of_utc"] = state.source_as_of.isoformat()
        receipt["game_status"] = state.status
        return state, receipt

    def fetch_espn_summary(self, sport: str, event_id: str
                           ) -> tuple[Mapping[str, Any], dict[str, Any]]:
        """Fetch the ESPN summary payload (injuries section) for one event."""
        from .live_participation import ESPN_SUMMARY_URLS
        sport = str(sport).upper()
        if sport not in ESPN_SUMMARY_URLS:
            raise LiveStateError("SPORT_INVALID")
        url = ESPN_SUMMARY_URLS[sport].format(event_id=event_id)
        data, receipt = self._fetch(url)
        receipt["event_id"] = str(event_id)
        return data if isinstance(data, dict) else {}, receipt

    def discover_live_events(self, sport: str) -> list[dict[str, Any]]:
        """List today's ESPN scoreboard events with coarse status."""
        sport = str(sport).upper()
        if sport not in ESPN_SCOREBOARD_URLS:
            raise LiveStateError("SPORT_INVALID")
        data, receipt = self._fetch(ESPN_SCOREBOARD_URLS[sport])
        out = []
        for item in (data or {}).get("events") or []:
            home, away = _competitor_names(item)
            comp = (item.get("competitions") or [{}])[0]
            st = (comp.get("status") or {}).get("type") or {}
            out.append({
                "event_id": str(item.get("id")),
                "home": home,
                "away": away,
                "date": item.get("date"),
                "state": str(st.get("state") or ""),
                "detail": str(st.get("shortDetail") or st.get("description") or ""),
            })
        return out


def _norm_name(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _name_match(candidate: str, wanted: str) -> bool:
    a, b = _norm_name(candidate), _norm_name(wanted)
    return bool(a and b and (a == b or a.endswith(b) or b.endswith(a)))


def _competitor_names(event: Mapping[str, Any]) -> tuple[str, str]:
    comp = (event.get("competitions") or [{}])[0]
    home = away = ""
    for comp_entry in comp.get("competitors") or []:
        team = comp_entry.get("team") or {}
        name = str(team.get("displayName") or team.get("shortDisplayName")
                   or team.get("abbreviation") or "")
        if comp_entry.get("homeAway") == "home":
            home = name
        elif comp_entry.get("homeAway") == "away":
            away = name
    return home, away


__all__ = [
    "LIVE_POLL_CADENCE_SECONDS",
    "LIVE_MAX_REQUESTS_PER_MINUTE",
    "LIVE_REQUEST_SPACING_SECONDS",
    "LIVE_STATE_STALENESS_THRESHOLD_SECONDS",
    "LiveRateLimited",
    "LiveFetchError",
    "PollBudget",
    "LivePoller",
]
