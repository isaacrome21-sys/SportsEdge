"""Independent public CFB player game-log history from free ESPN endpoints.

Mirrors the NFL collector. Resolves player by display name, fetches college
football gamelog, returns prior completed games. No odds, no trusted features.
Requires unique pregame fixture and at least 5 prior games. When the
current-season gamelog yields fewer than 5 verified priors, fill from up to
two immediately preceding seasons for the same athlete (?season=YYYY), so a
transfer's prior-school games stay reachable. Every historical row remains
subject to the same date and schema safeguards. Each returned game also
carries its season, its opponent and -- where the event metadata supports
it -- the team the player played for in that game, so games from two
different schools are never silently pooled unattributed. Research only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re
from .football_gamelog_decode import decode_football_event, FootballGamelogSchemaError
from .football_roster_lookup import lookup_matchup_roster_player, FootballRosterAmbiguity

ESPN_SEARCH = "https://site.web.api.espn.com/apis/search/v2"
ESPN_GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/football/college-football/athletes"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"


class MissingCFBHistory(ValueError):
    pass


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise MissingCFBHistory(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise MissingCFBHistory(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _gamelog_stats_lookup(data):
    """Bind eventId -> stats from ESPN seasonTypes category entries.

    The live ESPN gamelog keeps event metadata in a top-level ``events``
    map, separate from category event stats. All raw stat lists still
    require the explicit top-level `names` metadata for unambiguous field
    identity (enforced by the decoder). Repeated event IDs may be deduped
    only if the corresponding stats are identical.
    """
    lookup = {}
    season_types = data.get("seasonTypes")
    if season_types is None:
        return lookup
    if not isinstance(season_types, list):
        raise MissingCFBHistory("ESPN_GAMELOG_SEASON_TYPES_NOT_LIST")
    for season in season_types:
        if not isinstance(season, dict):
            raise MissingCFBHistory("ESPN_GAMELOG_SEASON_TYPE_NOT_OBJECT")
        categories = season.get("categories")
        if categories is None:
            continue
        if not isinstance(categories, list):
            raise MissingCFBHistory("ESPN_GAMELOG_CATEGORIES_NOT_LIST")
        for category in categories:
            if not isinstance(category, dict):
                raise MissingCFBHistory("ESPN_GAMELOG_CATEGORY_NOT_OBJECT")
            cat_events = category.get("events")
            if cat_events is None:
                continue
            if not isinstance(cat_events, list):
                raise MissingCFBHistory("ESPN_GAMELOG_CATEGORY_EVENTS_NOT_LIST")
            for entry in cat_events:
                if not isinstance(entry, dict):
                    raise MissingCFBHistory("ESPN_GAMELOG_CATEGORY_EVENT_NOT_OBJECT")
                event_id = str(entry.get("eventId") or "").strip()
                if not event_id or "stats" not in entry:
                    continue
                stats = entry["stats"]
                if event_id in lookup:
                    if lookup[event_id] != stats:
                        raise MissingCFBHistory(
                            "ESPN_GAMELOG_STATS_CONFLICT:" + event_id)
                    continue
                lookup[event_id] = stats
    return lookup


def _gamelog_events(data, stats_lookup):
    """Normalize metadata maps and legacy event lists to named stat events.

    Current shape: ``events`` is a dict keyed by event id holding metadata
    only; stats are bound from the seasonTypes lookup. Legacy shape:
    ``events`` is a list of event objects, usually carrying inline stats.
    A mapping-key / metadata-id conflict is counted as invalid, never
    repaired by guessing. An event with no stats remains invalid; missing
    values are not zero-filled. Any other ``events`` type fails closed.
    """
    raw = data.get("events")
    if raw is None:
        raw = []
    events = []
    rejected = 0
    if isinstance(raw, dict):
        for key, meta in raw.items():
            if not isinstance(meta, dict):
                rejected += 1
                continue
            event_id = str(key or "").strip()
            meta_id = str(meta.get("id") or "").strip()
            if meta_id and event_id and meta_id != event_id:
                rejected += 1
                continue
            if not event_id:
                event_id = meta_id
            merged = dict(meta)
            merged["id"] = event_id
            if "stats" not in merged and event_id in stats_lookup:
                merged["stats"] = stats_lookup[event_id]
            events.append(merged)
    elif isinstance(raw, list):
        for meta in raw:
            if not isinstance(meta, dict):
                rejected += 1
                continue
            merged = dict(meta)
            event_id = str(merged.get("id") or "").strip()
            if "stats" not in merged and event_id and event_id in stats_lookup:
                merged["stats"] = stats_lookup[event_id]
            events.append(merged)
    else:
        raise MissingCFBHistory("ESPN_GAMELOG_EVENTS_NOT_LIST")
    return events, rejected


def _season_year_of(moment):
    """The CFB season's nominal year, including January bowls/playoffs."""
    return moment.year if moment.month >= 3 else moment.year - 1


def _response_season_year(data):
    """Use the season declared by ESPN when present."""
    years = []
    for season in data.get("seasonTypes") or []:
        if not isinstance(season, dict):
            continue
        match = re.match(r"\s*((?:19|20)\d{2})\b",
                         str(season.get("displayName") or ""))
        if match:
            years.append(int(match.group(1)))
    return max(years) if years else None


def _gamelog_event_types(data):
    """Bind game event ID to regular/postseason, without inferring from dates."""
    result = {}
    for season in data.get("seasonTypes") or []:
        if not isinstance(season, dict):
            continue
        label = str(season.get("displayName") or "").lower()
        kind = ("postseason" if "postseason" in label else
                "regular" if "regular" in label else "unknown")
        for category in season.get("categories") or []:
            if not isinstance(category, dict):
                continue
            for event in category.get("events") or []:
                if isinstance(event, dict):
                    event_id = str(event.get("eventId") or "").strip()
                    if event_id:
                        old = result.get(event_id)
                        if old and old != kind:
                            raise MissingCFBHistory(
                                "ESPN_GAMELOG_SEASON_TYPE_CONFLICT:" + event_id)
                        result[event_id] = kind
    return result


def _gamelog_attribution(event):
    """(opponent_name, player_team_id) stated by the event metadata.

    The player's own team is identified by elimination: the metadata names
    both team ids and the opponent; the non-opponent id is the player's
    team. Anything missing or ambiguous stays unattributed (None) -- team
    attribution is provenance, never guessed and never a filter.
    """
    opponent = event.get("opponent")
    opp_name = None
    opp_id = ""
    if isinstance(opponent, dict):
        opp_name = (opponent.get("displayName")
                    or opponent.get("abbreviation") or None)
        opp_id = str(opponent.get("id") or "")
    home_id = str(event.get("homeTeamId") or "")
    away_id = str(event.get("awayTeamId") or "")
    team_id = None
    if opp_id and home_id and away_id and home_id != away_id:
        if opp_id == home_id:
            team_id = away_id
        elif opp_id == away_id:
            team_id = home_id
    return opp_name, team_id


def _gamelog_history(data, *, now, kickoff, season_year):
    """Return (games, schema rejection count, per-reason counts).

    Games are dated and named-stat decoded; the CFB PIT filter is the
    pre-existing one: strictly before both the as-of instant and the
    fixture kickoff. Post-as-of or post-kickoff events are excluded, not
    counted as schema rejections.
    """
    stats_lookup = _gamelog_stats_lookup(data)
    event_types = _gamelog_event_types(data)
    events, rejected = _gamelog_events(data, stats_lookup)
    hist = []
    reasons = {}
    if rejected:
        reasons["GAMEDAY_EVENT_METADATA_INVALID"] = rejected
    for event in events:
        try:
            day = _clock(event.get("gameDate") or event.get("date"),
                         "GAMELOG_DATE")
            if day >= now or day >= kickoff:
                continue
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                raise MissingCFBHistory("PRIOR_GAME_ID_UNVERIFIED")
            actual = decode_football_event(data, event)
            opp_name, team_id = _gamelog_attribution(event)
            hist.append((day, event_id, actual, season_year,
                         event_types.get(event_id, "unknown"),
                         opp_name, team_id))
        except (FootballGamelogSchemaError, ValueError, TypeError,
                KeyError, MissingCFBHistory) as exc:
            rejected += 1
            reason = str(exc).split(":", 1)[0] or type(exc).__name__
            reasons[reason] = reasons.get(reason, 0) + 1
    return hist, rejected, reasons


def _merge_season_history(base, extra):
    """Deduplicate equal games and reject same-event conflicting statistics."""
    seen = {entry[1]: entry[2] for entry in base}
    out = list(base)
    for entry in extra:
        event_id, stats = entry[1], entry[2]
        if event_id in seen:
            if seen[event_id] != stats:
                raise MissingCFBHistory("ESPN_GAMELOG_STATS_CONFLICT:" + event_id)
            continue
        seen[event_id] = stats
        out.append(entry)
    return out


def public_json(url):
    try:
        request = Request(url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                                        "Accept": "application/json"})
        with urlopen(request, timeout=12) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read(4_000_000))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return None


class CFBPlayerPublicSource:
    def __init__(self, *, getter=None):
        self.getter = getter or public_json
        self.cache = {}

    def _fetch(self, url):
        if url not in self.cache:
            try:
                data = self.getter(url)
                self.cache[url] = data if isinstance(data, dict) else None
            except (OSError, ValueError, TypeError, TimeoutError):
                self.cache[url] = None
        return self.cache[url]

    def _game(self, away, home, owner_kickoff, now):
        if owner_kickoff <= now:
            raise MissingCFBHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
        selected = []
        for date in {(owner_kickoff - timedelta(days=1)).date(), owner_kickoff.date()}:
            url = ESPN_SCOREBOARD + "?" + urlencode({"dates": date.strftime("%Y%m%d")})
            resp = self._fetch(url)
            if resp is None or not isinstance(resp.get("events"), list):
                continue
            for event in resp["events"]:
                comps = event.get("competitions") or []
                if not comps:
                    continue
                cs = comps[0].get("competitors") or []
                home_cs = next((c for c in cs if c.get("homeAway") == "home"), None)
                away_cs = next((c for c in cs if c.get("homeAway") == "away"), None)
                if not home_cs or not away_cs:
                    continue
                if (_norm((home_cs.get("team") or {}).get("displayName")) != _norm(home) or
                    _norm((away_cs.get("team") or {}).get("displayName")) != _norm(away)):
                    continue
                try:
                    start = _clock(event.get("date"), "CFB_SCHEDULE_START")
                except MissingCFBHistory:
                    continue
                if abs((start - owner_kickoff).total_seconds()) > 4 * 3600:
                    continue
                selected.append(event)
        unique = {str(e.get("id")): e for e in selected if e.get("id")}
        if len(unique) != 1:
            raise MissingCFBHistory("CFB_PUBLIC_FIXTURE_NOT_UNIQUELY_VERIFIED")
        return next(iter(unique.values()))

    def _resolve_athlete(self, player_name, allowed_team_ids):
        # Resolve exact identity against the two independently verified fixture
        # teams first. ESPN global search often omits current team identifiers.
        try:
            roster_player = lookup_matchup_roster_player(
                self._fetch, league="college-football",
                team_ids=allowed_team_ids, player_name=player_name)
        except FootballRosterAmbiguity as exc:
            raise MissingCFBHistory(str(exc)) from exc
        if roster_player is not None:
            return roster_player
        url = ESPN_SEARCH + "?" + urlencode({"query": player_name, "limit": "10", "type": "player"})
        data = self._fetch(url)
        items = ((data or {}).get("results") or [{}])[0].get("contents") or []
        matches = []
        for item in items:
            athlete = (item.get("player") or {})
            if _norm(athlete.get("displayName") or athlete.get("fullName")) != _norm(player_name):
                continue
            team = athlete.get("team") or {}
            tid = str(team.get("id") or "") if isinstance(team, dict) else ""
            # A global name match without independently verified current
            # team membership is NOT enough to originate a player wager.
            if tid in allowed_team_ids:
                matches.append(athlete)
        if len(matches) != 1:
            raise MissingCFBHistory("PLAYER_NOT_UNIQUELY_RESOLVED_FROM_ESPN_SEARCH")
        return matches[0]

    def prior_games(self, *, away, home, player_name, owner_kickoff,
                    as_of, max_games=10):
        now = _clock(as_of, "MODEL_AS_OF")
        proposed = _clock(owner_kickoff, "OWNER_GAME_START")
        game = self._game(away, home, proposed, now)
        kickoff = _clock(game.get("date"), "CFB_SCHEDULE_START")
        if kickoff <= now:
            raise MissingCFBHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")

        competitors = ((game.get("competitions") or [{}])[0].get("competitors") or [])
        allowed_team_ids = {str((c.get("team") or {}).get("id") or "")
                            for c in competitors if isinstance(c, dict)}
        if len(allowed_team_ids) != 2 or "" in allowed_team_ids:
            raise MissingCFBHistory("ESPN_FIXTURE_TEAM_IDS_UNVERIFIED")
        athlete = self._resolve_athlete(player_name, allowed_team_ids)
        athlete_id = str(athlete.get("id") or "")
        if not athlete_id:
            raise MissingCFBHistory("ATHLETE_ID_MISSING")

        url = f"{ESPN_GAMELOG}/{athlete_id}/gamelog"
        data = self._fetch(url)
        if not isinstance(data, dict):
            raise MissingCFBHistory("CFB_GAMELOG_UNAVAILABLE")

        # The current-season view is sufficient when it contains at least
        # five verified games. Previous seasons are queried only if needed,
        # so a transfer's prior-school games remain reachable.
        current_year = (_response_season_year(data) or
                        _season_year_of(kickoff))
        hist, invalid_schema, reject_reasons = _gamelog_history(
            data, now=now, kickoff=kickoff, season_year=current_year)
        prior_season_years = []
        if len({entry[1] for entry in hist}) < 5:
            for year in (current_year - 1, current_year - 2):
                prior_season_years.append(year)
                prior_data = self._fetch(f"{url}?season={year}")
                if not isinstance(prior_data, dict):
                    reject_reasons["PRIOR_SEASON_UNAVAILABLE"] = (
                        reject_reasons.get("PRIOR_SEASON_UNAVAILABLE", 0) + 1)
                    continue
                extra, rejected, reasons = _gamelog_history(
                    prior_data, now=now, kickoff=kickoff,
                    season_year=(_response_season_year(prior_data) or year))
                invalid_schema += rejected
                for reason, count in reasons.items():
                    reject_reasons[reason] = reject_reasons.get(reason, 0) + count
                hist = _merge_season_history(hist, extra)
                if len({entry[1] for entry in hist}) >= 5:
                    break

        hist.sort(key=lambda x: x[0], reverse=True)
        latest = []
        seen = set()
        for prior in hist:
            if prior[1] in seen:
                continue
            seen.add(prior[1])
            latest.append(prior)
            if len(latest) >= max_games:
                break
        if len(latest) < 5:
            raise MissingCFBHistory("FEWER_THAN_FIVE_VERIFIED_NAMED_PRIOR_GAMES")

        dates = [d.isoformat() for d, *_ in latest]
        return {
            "game_id": str(game.get("id") or ""),
            "player_id": athlete_id,
            "player_name": athlete.get("displayName") or player_name,
            "home_team": home, "away_team": away,
            "kickoff_utc": kickoff.isoformat(), "source_as_of_utc": now.isoformat(),
            "prior_game_times_utc": dates,
            "prior_game_seasons": [
                f"{year}-{kind}" for _, _, _, year, kind, _, _ in latest],
            "prior_game_opponents": [opp for *_, opp, _ in latest],
            "prior_game_team_ids": [tid for *_, tid in latest],
            "prior_season_history_years": prior_season_years,
            "features": {"game_history": [stats for _, _, stats, *_ in latest]},
            "explicit_stat_fields": sorted(set().union(*(set(x[2]) for x in latest))),
            "schema_rejected_prior_events": invalid_schema,
            "schema_rejected_prior_reasons": dict(sorted(reject_reasons.items())),
            "source_endpoint": url,
            "prior_game_count": len(latest),
        }
