"""Verified free ESPN data acquisition for NBA (game markets + player history).

Sources (all free, public, no odds):
  - Scoreboard (fixtures + results):
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
  - Teams registry:
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams
  - Team roster (player identity verification):
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/roster
  - Player search (athlete id lookup; team membership is NOT trusted from here):
    https://site.web.api.espn.com/apis/search/v2
  - Player gamelog (per-player history; shape verified live 2026-10-11):
    https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog

Fail-closed: every unverified shape raises NBADataError with an explicit
reason code. Research only; no betting authority.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NBA_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
NBA_SEARCH = "https://site.web.api.espn.com/apis/search/v2"
NBA_GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes"
NBA_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"

NBA_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
USER_AGENT = "SportsEdge-free-research/1.0"


def _norm_name(value) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())

# 30 NBA teams verified live from the ESPN teams endpoint on 2026-10-11.
# Snapshot: tests/fixtures/nba/nba_teams_registry.json
NBA_TEAMS = (
    {"id": "1", "abbreviation": "ATL", "displayName": "Atlanta Hawks"},
    {"id": "2", "abbreviation": "BOS", "displayName": "Boston Celtics"},
    {"id": "17", "abbreviation": "BKN", "displayName": "Brooklyn Nets"},
    {"id": "30", "abbreviation": "CHA", "displayName": "Charlotte Hornets"},
    {"id": "4", "abbreviation": "CHI", "displayName": "Chicago Bulls"},
    {"id": "5", "abbreviation": "CLE", "displayName": "Cleveland Cavaliers"},
    {"id": "6", "abbreviation": "DAL", "displayName": "Dallas Mavericks"},
    {"id": "7", "abbreviation": "DEN", "displayName": "Denver Nuggets"},
    {"id": "8", "abbreviation": "DET", "displayName": "Detroit Pistons"},
    {"id": "9", "abbreviation": "GS", "displayName": "Golden State Warriors"},
    {"id": "10", "abbreviation": "HOU", "displayName": "Houston Rockets"},
    {"id": "11", "abbreviation": "IND", "displayName": "Indiana Pacers"},
    {"id": "12", "abbreviation": "LAC", "displayName": "LA Clippers"},
    {"id": "13", "abbreviation": "LAL", "displayName": "Los Angeles Lakers"},
    {"id": "29", "abbreviation": "MEM", "displayName": "Memphis Grizzlies"},
    {"id": "14", "abbreviation": "MIA", "displayName": "Miami Heat"},
    {"id": "15", "abbreviation": "MIL", "displayName": "Milwaukee Bucks"},
    {"id": "16", "abbreviation": "MIN", "displayName": "Minnesota Timberwolves"},
    {"id": "3", "abbreviation": "NO", "displayName": "New Orleans Pelicans"},
    {"id": "18", "abbreviation": "NY", "displayName": "New York Knicks"},
    {"id": "25", "abbreviation": "OKC", "displayName": "Oklahoma City Thunder"},
    {"id": "19", "abbreviation": "ORL", "displayName": "Orlando Magic"},
    {"id": "20", "abbreviation": "PHI", "displayName": "Philadelphia 76ers"},
    {"id": "21", "abbreviation": "PHX", "displayName": "Phoenix Suns"},
    {"id": "22", "abbreviation": "POR", "displayName": "Portland Trail Blazers"},
    {"id": "23", "abbreviation": "SAC", "displayName": "Sacramento Kings"},
    {"id": "24", "abbreviation": "SA", "displayName": "San Antonio Spurs"},
    {"id": "28", "abbreviation": "TOR", "displayName": "Toronto Raptors"},
    {"id": "26", "abbreviation": "UTAH", "displayName": "Utah Jazz"},
    {"id": "27", "abbreviation": "WSH", "displayName": "Washington Wizards"},
)

_TEAM_BY_ID = {t["id"]: t for t in NBA_TEAMS}
_TEAM_BY_ABBR = {t["abbreviation"]: t for t in NBA_TEAMS}
_TEAM_BY_NAME = {_norm_name(t["displayName"]): t for t in NBA_TEAMS}


class NBADataError(ValueError):
    """Fail-closed reason-coded error for unverified NBA data."""


def team_by_id(team_id: str) -> dict:
    team = _TEAM_BY_ID.get(str(team_id).strip())
    if team is None:
        raise NBADataError("NBA_TEAM_ID_NOT_IN_VERIFIED_REGISTRY:" + str(team_id))
    return team


def team_by_abbreviation(abbr: str) -> dict:
    team = _TEAM_BY_ABBR.get(str(abbr or "").strip().upper())
    if team is None:
        raise NBADataError("NBA_TEAM_ABBR_NOT_IN_VERIFIED_REGISTRY:" + str(abbr))
    return team


def team_by_display_name(name: str) -> dict:
    team = _TEAM_BY_NAME.get(_norm_name(name))
    if team is None:
        raise NBADataError("NBA_TEAM_NAME_NOT_IN_VERIFIED_REGISTRY:" + str(name))
    return team


def _clock(value, name: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise NBADataError(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise NBADataError(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def public_json(url: str):
    """GET JSON from a free public endpoint; None on transport failure."""
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read(8_000_000))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return None


class NBASource:
    """Injectable-fetch ESPN NBA source. ``getter(url)`` returns parsed JSON."""

    def __init__(self, *, getter=None):
        self.getter = getter or public_json
        self.cache: dict[str, object] = {}

    def _fetch(self, url: str):
        if url not in self.cache:
            try:
                data = self.getter(url)
            except (OSError, ValueError, TypeError, TimeoutError):
                data = None
            self.cache[url] = data if isinstance(data, dict) else None
        return self.cache[url]

    # ---- scoreboard: fixtures + results ---------------------------------

    def scoreboard(self, dates: str) -> list:
        """Fetch one scoreboard page for ``dates`` = YYYYMMDD."""
        d = str(dates or "").strip()
        if len(d) != 8 or not d.isdigit():
            raise NBADataError("NBA_DATES_INVALID:" + d)
        url = NBA_SCOREBOARD + "?" + urlencode({"dates": d, "limit": 50})
        data = self._fetch(url)
        if data is None:
            raise NBADataError("NBA_SCOREBOARD_UNAVAILABLE:" + d)
        events = data.get("events")
        if not isinstance(events, list):
            raise NBADataError("NBA_SCOREBOARD_EVENTS_NOT_LIST:" + d)
        return events

    @staticmethod
    def _competitors(event: dict):
        competitions = event.get("competitions") or []
        if not competitions or not isinstance(competitions[0], dict):
            raise NBADataError("NBA_COMPETITION_MISSING:" + str(event.get("id")))
        competitors = competitions[0].get("competitors") or []
        home = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "away"), None)
        if home is None or away is None:
            raise NBADataError("NBA_COMPETITORS_UNVERIFIED:" + str(event.get("id")))
        return home, away

    def resolve_fixture(self, *, away_name: str, home_name: str, owner_tipoff: str, as_of: str) -> dict:
        """Resolve the unique pregame fixture for the named matchup.

        Returns the ESPN event dict. Fails closed unless exactly one matching
        pre-tipoff event is found on the scoreboard days around the tipoff.
        """
        now = _clock(as_of, "NBA_MODEL_AS_OF")
        proposed = _clock(owner_tipoff, "NBA_OWNER_TIPOFF")
        if proposed <= now:
            raise NBADataError("NBA_STARTED_GAME_REQUIRES_VERIFIED_LIVE_ENGINE")
        want_home = _norm_name(home_name)
        want_away = _norm_name(away_name)
        if not want_home or not want_away:
            raise NBADataError("NBA_FIXTURE_TEAM_NAMES_REQUIRED")
        selected = []
        for day in {(proposed - timedelta(days=1)).date(), proposed.date()}:
            try:
                events = self.scoreboard(day.strftime("%Y%m%d"))
            except NBADataError:
                continue
            for event in events:
                if not isinstance(event, dict):
                    continue
                try:
                    home_c, away_c = self._competitors(event)
                    got_home = _norm_name((home_c.get("team") or {}).get("displayName"))
                    got_away = _norm_name((away_c.get("team") or {}).get("displayName"))
                    if got_home != want_home or got_away != want_away:
                        continue
                    start = _clock(event.get("date"), "NBA_SCHEDULE_START")
                except NBADataError:
                    continue
                if abs((start - proposed).total_seconds()) > 3 * 3600:
                    continue
                selected.append(event)
        unique = {str(e.get("id")): e for e in selected if e.get("id")}
        if len(unique) != 1:
            raise NBADataError("NBA_PUBLIC_FIXTURE_NOT_UNIQUELY_VERIFIED")
        return next(iter(unique.values()))

    def parse_completed_games(self, events: list,
                              skip_unregistered_teams: bool = False) -> list:
        """Parse scoreboard events -> completed games with verified scores.

        Returns [{event_id, tipoff, home_team_id, away_team_id,
        home_score, away_score}]. Non-completed events are skipped; completed
        events with missing/malformed scores fail closed. Team identity is
        verified against the NBA_TEAMS registry by ESPN team id.

        When ``skip_unregistered_teams`` is True, completed events involving
        teams outside the 30-team registry (e.g. All-Star exhibitions such as
        "Team Chuck"/"Team Kenny") are skipped instead of raising; the
        default False keeps the strict fail-closed behavior for pregame paths.
        """
        games = []
        for event in events:
            if not isinstance(event, dict):
                continue
            status = event.get("status") or {}
            stype = status.get("type") or {}
            if stype.get("completed") is not True:
                continue  # no verified outcome yet
            event_id = str(event.get("id") or "").strip()
            tipoff = str(event.get("date") or "").strip()
            if not event_id or not tipoff:
                raise NBADataError("NBA_EVENT_IDENTITY_UNVERIFIED")
            _clock(tipoff, "NBA_TIPOFF")
            home_c, away_c = self._competitors(event)
            home_team = (home_c.get("team") or {})
            away_team = (away_c.get("team") or {})
            home_id = str(home_team.get("id") or "").strip()
            away_id = str(away_team.get("id") or "").strip()
            # Team identity must resolve in the verified registry.
            try:
                team_by_id(home_id)
                team_by_id(away_id)
            except NBADataError:
                if skip_unregistered_teams:
                    continue  # e.g. All-Star exhibitions; not league games
                raise
            if home_id == away_id:
                raise NBADataError("NBA_FIXTURE_TEAMS_IDENTICAL:" + event_id)
            try:
                home_score = int(str(home_c.get("score")).strip())
                away_score = int(str(away_c.get("score")).strip())
            except (ValueError, TypeError, AttributeError) as exc:
                raise NBADataError("NBA_FINAL_SCORE_UNVERIFIED:" + event_id) from exc
            if home_score < 0 or away_score < 0:
                raise NBADataError("NBA_FINAL_SCORE_NEGATIVE:" + event_id)
            games.append({
                "event_id": event_id,
                "tipoff": tipoff,
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_score": home_score,
                "away_score": away_score,
            })
        return games

    # ---- player identity --------------------------------------------------

    def roster_player_ids(self, team_id: str) -> dict:
        """Return {normalized_display_name: athlete_id} for a fixture team's roster."""
        tid = str(team_id).strip()
        team_by_id(tid)  # registry check first
        url = NBA_ROSTER_URL.format(team_id=quote(tid, safe=""))
        data = self._fetch(url)
        if data is None:
            raise NBADataError("NBA_ROSTER_UNAVAILABLE:" + tid)
        athletes = data.get("athletes")
        if not isinstance(athletes, list):
            raise NBADataError("NBA_ROSTER_ATHLETES_NOT_LIST:" + tid)
        roster_team = data.get("team") or {}
        if isinstance(roster_team, dict) and roster_team.get("id") is not None:
            if str(roster_team["id"]) != tid:
                raise NBADataError("NBA_ROSTER_TEAM_MISMATCH:" + tid)
        out = {}
        for entry in athletes:
            if not isinstance(entry, dict):
                continue
            athlete = entry.get("athlete") if isinstance(entry.get("athlete"), dict) else entry
            name = _norm_name(athlete.get("displayName") or athlete.get("fullName"))
            aid = str(athlete.get("id") or "").strip()
            if name and aid and name not in out:
                out[name] = aid
        return out

    def resolve_athlete(self, player_name: str, allowed_team_ids: set) -> dict:
        """Resolve a player name to {id, displayName} verified against fixture rosters.

        Roster-first (mirrors the NFL path): a unique exact-name match on one
        of the two independently verified fixture teams wins. ESPN global
        search is a fallback, but a search hit without verified roster
        membership is rejected (search team labels were observed stale live).
        """
        wanted = _norm_name(player_name)
        if not wanted:
            raise NBADataError("NBA_PLAYER_NAME_REQUIRED")
        ids = {str(x) for x in allowed_team_ids}
        if len(ids) != 2 or "" in ids:
            raise NBADataError("NBA_UNVERIFIED_MATCHUP_TEAM_IDS")
        roster_hits = []
        for tid in sorted(ids):
            try:
                roster = self.roster_player_ids(tid)
            except NBADataError:
                continue
            if wanted in roster:
                roster_hits.append((tid, roster[wanted]))
        if len(roster_hits) > 1:
            raise NBADataError("NBA_PLAYER_AMBIGUOUS_ACROSS_ROSTERS:" + player_name)
        if len(roster_hits) == 1:
            tid, aid = roster_hits[0]
            return {"id": aid, "displayName": player_name, "team_id": tid,
                    "via": "fixture_roster"}

        # Fallback: ESPN global search; require the hit to be an NBA player and
        # then confirm roster membership on a fixture team.
        url = NBA_SEARCH + "?" + urlencode({"query": player_name, "limit": "10", "type": "player"})
        data = self._fetch(url)
        items = ((data or {}).get("results") or [{}])[0].get("contents") or []
        matches = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "") != "player":
                continue
            if str(item.get("defaultLeagueSlug") or "") != "nba":
                continue
            if _norm_name(item.get("displayName")) != wanted:
                continue
            uid = str(item.get("uid") or "")
            m = re.search(r"~a:(\d+)$", uid)
            if not m:
                continue
            matches.append(m.group(1))
        matches = list(dict.fromkeys(matches))
        if len(matches) != 1:
            raise NBADataError("NBA_PLAYER_NOT_UNIQUELY_RESOLVED_FROM_ESPN_SEARCH:" + player_name)
        aid = matches[0]
        for tid in sorted(ids):
            try:
                roster = self.roster_player_ids(tid)
            except NBADataError:
                continue
            if aid in set(roster.values()):
                return {"id": aid, "displayName": player_name, "team_id": tid,
                        "via": "search_plus_roster"}
        raise NBADataError("NBA_SEARCH_HIT_NOT_ON_FIXTURE_ROSTER:" + player_name)

    # ---- player gamelog ----------------------------------------------------

    def gamelog(self, athlete_id: str, season: int | None = None) -> dict:
        """Fetch one athlete's gamelog page (shape verified live 2026-10-11)."""
        aid = str(athlete_id).strip()
        if not aid:
            raise NBADataError("NBA_ATHLETE_ID_REQUIRED")
        params = {}
        if season is not None:
            params["season"] = str(int(season))
        url = f"{NBA_GAMELOG}/{quote(aid, safe='')}/gamelog"
        if params:
            url += "?" + urlencode(params)
        data = self._fetch(url)
        if data is None:
            raise NBADataError("NBA_GAMELOG_UNAVAILABLE:" + aid)
        return data

    # ---- quarter scores (half/quarter market history) -----------------------

    def quarter_scores(self, event_id: str) -> dict:
        """Return verified per-quarter scores for a completed game.

        Source: the free ESPN NBA summary endpoint ``?event={event_id}``,
        ``header.competitions[0].competitors[].linescores`` (shape verified
        live 2026-10-11 on event 401704629). Returns
        {"event_id", "home_team_id", "away_team_id",
         "home_quarters": [q1..q4], "away_quarters": [q1..q4]}.
        Quarter sums must reconcile with the final score; otherwise the
        payload fails closed.
        """
        eid = str(event_id or "").strip()
        if not eid:
            raise NBADataError("NBA_EVENT_ID_REQUIRED")
        url = NBA_SUMMARY + "?" + urlencode({"event": eid})
        data = self._fetch(url)
        if data is None:
            raise NBADataError("NBA_SUMMARY_UNAVAILABLE:" + eid)
        header = data.get("header") or {}
        competitions = header.get("competitions") or []
        if not competitions or not isinstance(competitions[0], dict):
            raise NBADataError("NBA_SUMMARY_COMPETITION_MISSING:" + eid)
        competitors = competitions[0].get("competitors") or []
        home = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "away"), None)
        if home is None or away is None:
            raise NBADataError("NBA_SUMMARY_COMPETITORS_UNVERIFIED:" + eid)

        def quarters(comp, side: str) -> list[int]:
            linescores = comp.get("linescores")
            if not isinstance(linescores, list) or len(linescores) < 4:
                raise NBADataError(f"NBA_SUMMARY_LINESCORES_UNVERIFIED:{eid}:{side}")
            out = []
            for cell in linescores[:4]:
                try:
                    out.append(int(str((cell or {}).get("displayValue")).strip()))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise NBADataError(f"NBA_SUMMARY_QUARTER_SCORE_UNVERIFIED:{eid}:{side}") from exc
                if out[-1] < 0:
                    raise NBADataError(f"NBA_SUMMARY_QUARTER_SCORE_NEGATIVE:{eid}:{side}")
            return out

        home_q = quarters(home, "home")
        away_q = quarters(away, "away")
        home_id = str((home.get("team") or {}).get("id") or "").strip()
        away_id = str((away.get("team") or {}).get("id") or "").strip()
        team_by_id(home_id)
        team_by_id(away_id)
        try:
            home_final = int(str(home.get("score")).strip())
            away_final = int(str(away.get("score")).strip())
        except (ValueError, TypeError, AttributeError) as exc:
            raise NBADataError("NBA_SUMMARY_FINAL_SCORE_UNVERIFIED:" + eid) from exc
        if sum(home_q) != home_final or sum(away_q) != away_final:
            raise NBADataError("NBA_SUMMARY_QUARTERS_DO_NOT_RECONCILE:" + eid)
        return {
            "event_id": eid,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_quarters": home_q,
            "away_quarters": away_q,
            "home_first_half": sum(home_q[:2]),
            "away_first_half": sum(away_q[:2]),
        }
