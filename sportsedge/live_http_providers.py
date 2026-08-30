"""HTTP-backed live acquisition providers for RUN IT.

These providers are acquisition-only. Sportsbook prices are emitted as market
quotes and are never inserted into governed LIVE Model_P features.
"""

from __future__ import annotations

from collections import defaultdict
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
    """Public ESPN scoreboard discovery/state relay with strict provenance."""

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
            events.append(
                LiveEventRef(
                    sport=sport,
                    event_id=str(item.get("id")),
                    status=_event_status(item),
                    scheduled_start=_parse_dt(item.get("date"), now),
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
    """Automatic live quote provider using featured + discovered event markets.

    The provider first retrieves the featured board to resolve the provider event
    ID, then uses the event-markets endpoint to discover additional markets that
    are actually being offered. Additional markets are requested in chunks and
    normalized only when a complete two-way pair is present. Unknown or one-sided
    contracts remain DATA_GAPs rather than being invented.
    """

    name = "THE_ODDS_API"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        bookmakers: str | None = None,
        get_json: JsonGetter = _default_get_json,
        scan_additional_markets: bool = True,
    ):
        self.api_key = (api_key or os.getenv("SPORTSEDGE_ODDS_API_KEY", "")).strip()
        self.bookmakers = bookmakers or os.getenv("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings")
        self._get_json = get_json
        self.scan_additional_markets = scan_additional_markets

    def fetch_state(self, event: LiveEventRef) -> tuple[Mapping[str, object], datetime] | None:
        return None

    def _query(self, event: LiveEventRef, path: str, params: Mapping[str, object]) -> Any:
        query = urlencode({"apiKey": self.api_key, **params})
        return self._get_json(f"https://api.the-odds-api.com/v4/sports/{SPORT_ODDS_KEYS[event.sport]}/{path}?{query}")

    def _board(self, event: LiveEventRef) -> list[Mapping[str, Any]]:
        if not self.api_key:
            return []
        data = self._query(
            event,
            "odds",
            {
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
                "dateFormat": "iso",
                "bookmakers": self.bookmakers,
            },
        )
        return data if isinstance(data, list) else []

    def _match_game(self, event: LiveEventRef, board: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        for game in board:
            if _same_team(str(game.get("home_team", "")), event.home_team) and _same_team(
                str(game.get("away_team", "")), event.away_team
            ):
                return game
        return None

    def _available_market_keys(self, event: LiveEventRef, provider_event_id: str) -> tuple[str, ...]:
        if not self.scan_additional_markets:
            return ()
        data = self._query(
            event,
            f"events/{provider_event_id}/markets",
            {"regions": "us", "dateFormat": "iso"},
        )
        keys = set()
        bookmakers = data.get("bookmakers", []) if isinstance(data, Mapping) else []
        for book in bookmakers:
            if self.bookmakers and str(book.get("key", "")) not in set(self.bookmakers.split(",")):
                continue
            for market in book.get("markets") or []:
                key = market.get("key")
                if key:
                    keys.add(str(key))
        return tuple(sorted(keys - {"h2h", "spreads", "totals"}))

    def _event_odds(self, event: LiveEventRef, provider_event_id: str, keys: Sequence[str]) -> list[Mapping[str, Any]]:
        if not keys:
            return []
        data = self._query(
            event,
            f"events/{provider_event_id}/odds",
            {
                "regions": "us",
                "markets": ",".join(keys),
                "oddsFormat": "american",
                "dateFormat": "iso",
                "bookmakers": self.bookmakers,
            },
        )
        return [data] if isinstance(data, Mapping) else []

    def fetch_quotes(self, event: LiveEventRef, markets: Sequence[str]) -> Iterable[LiveMarketQuote]:
        wanted = set(markets)
        if not self.api_key:
            return ()
        retrieved = datetime.now(timezone.utc)
        board = self._board(event)
        game = self._match_game(event, board)
        if game is None:
            return ()

        rows = self._normalize_game(event, game, wanted, retrieved)
        provider_event_id = str(game.get("id") or "")
        if provider_event_id and self.scan_additional_markets:
            try:
                keys = self._available_market_keys(event, provider_event_id)
            except Exception:
                keys = ()
            for index in range(0, len(keys), 10):
                chunk = keys[index:index + 10]
                try:
                    extra_games = self._event_odds(event, provider_event_id, chunk)
                except Exception:
                    continue
                for extra in extra_games:
                    rows.extend(self._normalize_game(event, extra, wanted, retrieved))
        return tuple(rows)

    def _normalize_game(
        self,
        event: LiveEventRef,
        game: Mapping[str, Any],
        wanted: set[str],
        retrieved: datetime,
    ) -> list[LiveMarketQuote]:
        rows: list[LiveMarketQuote] = []
        for book in game.get("bookmakers") or []:
            book_name = str(book.get("key") or book.get("title") or "UNKNOWN")
            book_update = _parse_dt(book.get("last_update"), retrieved)
            for market in book.get("markets") or []:
                key = str(market.get("key") or "")
                market_name = self._market_name(event.sport, key)
                if market_name is None or market_name not in wanted:
                    continue
                source_as_of = _parse_dt(market.get("last_update"), book_update)
                for focal, opposite, contract in self._pairs(key, market.get("outcomes") or []):
                    rows.append(
                        self._quote(
                            event, book_name, market_name, contract,
                            focal, opposite, source_as_of, retrieved,
                        )
                    )
        return rows

    @staticmethod
    def _market_name(sport: str, key: str) -> str | None:
        if key == "h2h":
            return "MONEYLINE"
        if key == "spreads":
            return "SPREAD"
        if key == "totals":
            return "TOTAL"
        if key == "team_totals" or key == "alternate_team_totals":
            return "TEAM_TOTAL"
        if key == "alternate_totals":
            return "ALT_TOTAL"
        if key == "alternate_spreads":
            return "ALT_RUN_LINE" if sport == "MLB" else "ALT_SPREAD"
        if key.startswith("batter_"):
            return "BATTER_PROP" if sport == "MLB" else "PLAYER_PROP"
        if key.startswith("pitcher_"):
            return "PITCHER_PROP" if sport == "MLB" else "PLAYER_PROP"
        if key.startswith("player_"):
            return "PLAYER_PROP"
        if sport == "MLB" and "1st_5_innings" in key:
            if key.startswith("h2h"):
                return "F5_MONEYLINE"
            if key.startswith("spreads"):
                return "F5_RUN_LINE"
            if key.startswith("totals"):
                return "F5_TOTAL"
        if sport == "MLB" and "innings" in key:
            return "INNING_MONEYLINE" if key.startswith("h2h") else "INNING_TOTAL"
        if "_h1" in key or "1st_half" in key:
            if key.startswith("h2h"):
                return "1H_MONEYLINE"
            if key.startswith("spreads"):
                return "1H_SPREAD"
            if key.startswith("totals"):
                return "1H_TOTAL"
        if "_h2" in key or "2nd_half" in key:
            if key.startswith("h2h"):
                return "2H_MONEYLINE"
            if key.startswith("spreads"):
                return "2H_SPREAD"
            if key.startswith("totals"):
                return "2H_TOTAL"
        if any(token in key for token in ("_q1", "_q2", "_q3", "_q4")):
            if key.startswith("h2h"):
                return "QUARTER_MONEYLINE"
            if key.startswith("spreads"):
                return "QUARTER_SPREAD"
            if key.startswith("totals"):
                return "QUARTER_TOTAL"
        return None

    @staticmethod
    def _pairs(
        key: str, outcomes: Sequence[Mapping[str, Any]]
    ) -> tuple[tuple[Mapping[str, Any], Mapping[str, Any], str], ...]:
        usable = [o for o in outcomes if o.get("name") and o.get("price") is not None]
        if not usable:
            return ()

        names = {str(o.get("name")).lower() for o in usable}
        groups: dict[tuple[object, ...], list[Mapping[str, Any]]] = defaultdict(list)
        if names <= {"over", "under"} or names <= {"yes", "no"}:
            for outcome in usable:
                groups[(outcome.get("description"), outcome.get("point"))].append(outcome)
        elif key.startswith("spreads") or key == "alternate_spreads":
            for outcome in usable:
                point = outcome.get("point")
                groups[(abs(float(point)) if point is not None else None,)].append(outcome)
        else:
            groups[(None,)] = usable

        pairs = []
        for group_key, group in groups.items():
            if len(group) != 2:
                continue
            a, b = group
            descriptor = a.get("description") or b.get("description") or ""
            point = a.get("point") if a.get("point") is not None else b.get("point")
            contract = f"{key}:{descriptor}:{point}"
            pairs.append((a, b, contract))
        return tuple(pairs)

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
        focal_name = str(focal.get("description") or focal.get("name"))
        opposite_name = str(opposite.get("description") or opposite.get("name"))
        if focal.get("description"):
            focal_name = f"{focal.get('description')} {focal.get('name')} {focal.get('point', '')}".strip()
        if opposite.get("description"):
            opposite_name = f"{opposite.get('description')} {opposite.get('name')} {opposite.get('point', '')}".strip()
        return LiveMarketQuote(
            sport=event.sport,
            event_id=event.event_id,
            book=book,
            market=market,
            contract_key=contract,
            focal_selection=focal_name,
            opposite_selection=opposite_name,
            focal_odds=float(focal.get("price")),
            opposite_odds=float(opposite.get("price")),
            source_as_of=source_as_of,
            retrieved_at=retrieved,
            active=True,
            provider=self.name,
        )
