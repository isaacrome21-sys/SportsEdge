"""HTTP-backed live acquisition providers for RUN IT.

These providers are acquisition-only. Sportsbook prices are emitted as market
quotes and are never inserted into governed LIVE Model_P features.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .live_acquisition import LiveEventRef
from .live_markets import LiveMarketQuote


JsonGetter = Callable[[str], Any]

SPORT_ODDS_KEYS = {
    "MLB": "baseball_mlb",
    "NFL": "americanfootball_nfl",
    "CFB": "americanfootball_ncaaf",
}

ESPN_SCOREBOARD_URLS = {
    "MLB": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
    "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "CFB": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
}


def _default_get_json(url: str) -> Any:
    with urlopen(Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"}), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _parse_dt(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _norm_team(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _same_team(candidate: str, wanted: str) -> bool:
    a, b = _norm_team(candidate), _norm_team(wanted)
    return bool(a and b and (a == b or a.endswith(b) or b.endswith(a)))


def _event_status(item: Mapping[str, Any]) -> str:
    competition = (item.get("competitions") or [{}])[0]
    status = competition.get("status") or item.get("status") or {}
    status_type = status.get("type") or {}
    name = str(status_type.get("name") or "").upper()
    state = str(status_type.get("state") or "").lower()
    if any(token in name for token in ("CANCELED", "CANCELLED", "POSTPONED", "SUSPENDED")):
        return "SUSPENDED"
    if bool(status_type.get("completed")) or state == "post":
        return "FINAL"
    if state == "in":
        return "LIVE"
    return "PREGAME"


def _competitors(item: Mapping[str, Any]):
    competition = (item.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    return competition, home, away


def _team_name(competitor: Mapping[str, Any] | None) -> str:
    if not competitor:
        return ""
    team = competitor.get("team") or {}
    return str(team.get("displayName") or team.get("shortDisplayName") or team.get("abbreviation") or "")


class ESPNLiveStateProvider:
    """Public ESPN scoreboard discovery/state relay with strict provenance.

    Missing fields are left missing; sport adapters decide whether the state is
    sufficient for a governed model rather than this provider inventing values.
    """

    name = "ESPN_SCOREBOARD"

    def __init__(self, *, get_json: JsonGetter = _default_get_json):
        self._get_json = get_json

    def discover_events(self, sport: str) -> tuple[LiveEventRef, ...]:
        now = datetime.now(timezone.utc)
        data = self._get_json(ESPN_SCOREBOARD_URLS[sport])
        events: list[LiveEventRef] = []
        for item in data.get("events", []):
            _, home, away = _competitors(item)
            if not home or not away:
                continue
            start = _parse_dt(item.get("date"), now)
            events.append(
                LiveEventRef(
                    sport=sport,
                    event_id=str(item.get("id")),
                    status=_event_status(item),
                    scheduled_start=start,
                    home_team=_team_name(home),
                    away_team=_team_name(away),
                )
            )
        return tuple(events)

    def fetch_quotes(self, event: LiveEventRef, markets: Sequence[str]) -> Iterable[LiveMarketQuote]:
        return ()

    def fetch_state(self, event: LiveEventRef) -> tuple[Mapping[str, object], datetime] | None:
        data = self._get_json(ESPN_SCOREBOARD_URLS[event.sport])
        now = datetime.now(timezone.utc)
        for item in data.get("events", []):
            competition, home, away = _competitors(item)
            if not home or not away:
                continue
            home_names = [home.get("team", {}).get(k, "") for k in ("displayName", "shortDisplayName", "abbreviation")]
            away_names = [away.get("team", {}).get(k, "") for k in ("displayName", "shortDisplayName", "abbreviation")]
            id_match = str(item.get("id", "")) == event.event_id
            team_match = any(_same_team(n, event.home_team) for n in home_names) and any(
                _same_team(n, event.away_team) for n in away_names
            )
            if not (id_match or team_match):
                continue

            situation = competition.get("situation") or item.get("situation") or {}
            status = competition.get("status") or item.get("status") or {}
            state: dict[str, object] = {
                "period": status.get("period"),
                "clock_display": status.get("displayClock") or status.get("type", {}).get("shortDetail"),
                "home_score": int(float(home.get("score") or 0)),
                "away_score": int(float(away.get("score") or 0)),
                "event_status": _event_status(item),
            }
            if event.sport in {"NFL", "CFB"}:
                aliases = {
                    "down": ("down",),
                    "distance": ("distance",),
                    "yardline_100": ("yardLine", "yardline", "yardLine100"),
                    "timeouts_home": ("homeTimeouts", "timeoutsHome"),
                    "timeouts_away": ("awayTimeouts", "timeoutsAway"),
                    "plays_home": ("homePlays", "playsHome"),
                    "plays_away": ("awayPlays", "playsAway"),
                }
                for out_name, keys in aliases.items():
                    for key in keys:
                        if situation.get(key) is not None:
                            state[out_name] = situation[key]
                            break
                possession = situation.get("possession")
                if possession is not None:
                    state["possession_raw"] = possession
                    home_id = str(home.get("team", {}).get("id") or "")
                    away_id = str(away.get("team", {}).get("id") or "")
                    if str(possession) == home_id:
                        state["possession"] = "HOME"
                    elif str(possession) == away_id:
                        state["possession"] = "AWAY"
            else:
                aliases = {
                    "inning": ("inning", "period"),
                    "inning_half": ("inningHalf", "half"),
                    "outs": ("outs",),
                    "balls": ("balls",),
                    "strikes": ("strikes",),
                    "bases_occupied": ("basesOccupied",),
                    "batting_team": ("battingTeam",),
                }
                for out_name, keys in aliases.items():
                    for key in keys:
                        if situation.get(key) is not None:
                            state[out_name] = situation[key]
                            break

            source_as_of = _parse_dt(
                competition.get("status", {}).get("type", {}).get("lastUpdated")
                or item.get("status", {}).get("type", {}).get("lastUpdated"),
                now,
            )
            return state, source_as_of
        return None


class TheOddsAPILiveProvider:
    """Automatic main-market live quote provider using The Odds API.

    Main markets are pulled automatically. Provider-specific prop/derivative
    markets can be added separately without weakening paired-quote governance.
    """

    name = "THE_ODDS_API"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        bookmakers: str | None = None,
        get_json: JsonGetter = _default_get_json,
    ):
        self.api_key = (api_key or os.getenv("SPORTSEDGE_ODDS_API_KEY", "")).strip()
        self.bookmakers = bookmakers or os.getenv("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings")
        self._get_json = get_json

    def fetch_state(self, event: LiveEventRef) -> tuple[Mapping[str, object], datetime] | None:
        return None

    def _board(self, event: LiveEventRef) -> list[Mapping[str, Any]]:
        if not self.api_key:
            return []
        query = urlencode({
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "dateFormat": "iso",
            "bookmakers": self.bookmakers,
        })
        url = f"https://api.the-odds-api.com/v4/sports/{SPORT_ODDS_KEYS[event.sport]}/odds?{query}"
        data = self._get_json(url)
        return data if isinstance(data, list) else []

    def fetch_quotes(self, event: LiveEventRef, markets: Sequence[str]) -> Iterable[LiveMarketQuote]:
        wanted = set(markets)
        if not self.api_key:
            return ()
        retrieved = datetime.now(timezone.utc)
        rows: list[LiveMarketQuote] = []
        for game in self._board(event):
            if not (_same_team(str(game.get("home_team", "")), event.home_team) and _same_team(str(game.get("away_team", "")), event.away_team)):
                continue
            for book in game.get("bookmakers") or []:
                book_name = str(book.get("key") or book.get("title") or "UNKNOWN")
                book_update = _parse_dt(book.get("last_update"), retrieved)
                for market in book.get("markets") or []:
                    key = market.get("key")
                    outcomes = market.get("outcomes") or []
                    source_as_of = _parse_dt(market.get("last_update"), book_update)
                    if key == "h2h" and "MONEYLINE" in wanted:
                        pair = self._two_way(outcomes)
                        if pair:
                            a, b = pair
                            rows.append(self._quote(event, book_name, "MONEYLINE", "moneyline", a, b, source_as_of, retrieved))
                    elif key == "spreads" and "SPREAD" in wanted:
                        pair = self._two_way(outcomes)
                        if pair:
                            a, b = pair
                            point = a.get("point")
                            contract = f"spread:{a.get('name')}:{point}"
                            rows.append(self._quote(event, book_name, "SPREAD", contract, a, b, source_as_of, retrieved))
                    elif key == "totals" and "TOTAL" in wanted:
                        pair = self._two_way(outcomes)
                        if pair:
                            a, b = pair
                            point = a.get("point")
                            contract = f"total:{point}"
                            rows.append(self._quote(event, book_name, "TOTAL", contract, a, b, source_as_of, retrieved))
            break
        return tuple(rows)

    @staticmethod
    def _two_way(outcomes: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
        usable = [o for o in outcomes if o.get("name") and o.get("price") is not None]
        if len(usable) != 2:
            return None
        return usable[0], usable[1]

    def _quote(
        self,
        event: LiveEventRef,
        book: str,
        market: str,
        contract: str,
        focal: Mapping[str, Any],
        opposite: Mapping[str, Any],
        source_as_of: datetime,
        retrieved: datetime,
    ) -> LiveMarketQuote:
        return LiveMarketQuote(
            sport=event.sport,
            event_id=event.event_id,
            book=book,
            market=market,
            contract_key=contract,
            focal_selection=str(focal.get("name")),
            opposite_selection=str(opposite.get("name")),
            focal_odds=float(focal.get("price")),
            opposite_odds=float(opposite.get("price")),
            source_as_of=source_as_of,
            retrieved_at=retrieved,
            active=True,
            provider=self.name,
        )
