"""Independent public NBA player game-log history from free ESPN endpoints.

Mirrors sportsedge.nfl_public_player_history for the NBA gamelog shape
(verified live 2026-10-11):

  1. resolve the unique pregame fixture on the ESPN NBA scoreboard
  2. resolve the athlete: fixture-roster first, ESPN search as fallback with
     roster-membership confirmation (search team labels observed stale)
  3. fetch gamelog pages across the current and prior seasons
     (?season= spans seasons so the games gate is reachable early in the year)
  4. decode only regular-season games; preseason/postseason are excluded
     (different rotations/game state) and recorded as skipped
  5. require >= MIN_PRIOR_GAMES verified prior games before tipoff

No odds, no tracking data, no trusted caller features. Research only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .espn_verified_source import NBASource, NBADataError, _clock, _norm_name
from .nba_gamelog_decode import (
    NBAGamelogSchemaError,
    decode_nba_gamelog_event,
    iter_gamelog_games,
)

MIN_PRIOR_GAMES = 5


class MissingNBAHistory(ValueError):
    pass


def _season_candidates(game_season_year: int | None) -> list[int]:
    """Season params to query: current season year, then up to 2 priors.

    ESPN ``?season=YYYY`` selects the season ending in year YYYY
    (season=2025 -> 2024-25). The default page is the current season.
    """
    if game_season_year is None:
        return [None]
    return [None, game_season_year - 1, game_season_year - 2]


class NBAPublicPlayerHistory:
    def __init__(self, *, source: NBASource | None = None):
        self.source = source or NBASource()

    def prior_games(self, *, away_name: str, home_name: str, player_name: str,
                    owner_tipoff: str, as_of: str, season_year: int | None = None,
                    max_games: int = 12, min_games: int = MIN_PRIOR_GAMES) -> dict:
        """Return verified prior regular-season games for a named NBA player."""
        src = self.source
        now = _clock(as_of, "NBA_MODEL_AS_OF")
        proposed = _clock(owner_tipoff, "NBA_OWNER_TIPOFF")

        try:
            game = src.resolve_fixture(away_name=away_name, home_name=home_name,
                                       owner_tipoff=owner_tipoff, as_of=as_of)
        except NBADataError as exc:
            raise MissingNBAHistory(str(exc)) from exc
        tipoff = _clock(game.get("date"), "NBA_SCHEDULE_START")

        competitors = ((game.get("competitions") or [{}])[0].get("competitors") or [])
        team_ids = set()
        team_abbr = {}
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            team = comp.get("team") or {}
            tid = str(team.get("id") or "").strip()
            if tid:
                team_ids.add(tid)
                team_abbr[tid] = str(team.get("abbreviation") or "").strip().upper()
        if len(team_ids) != 2:
            raise MissingNBAHistory("NBA_FIXTURE_TEAM_IDS_UNVERIFIED")

        try:
            athlete = src.resolve_athlete(player_name, team_ids)
        except NBADataError as exc:
            raise MissingNBAHistory(str(exc)) from exc
        athlete_id = athlete["id"]
        athlete_team_id = athlete["team_id"]

        hist = []
        invalid_schema = 0
        skipped_non_regular = 0
        seen = set()
        for season in _season_candidates(season_year):
            try:
                data = src.gamelog(athlete_id, season=season)
            except NBADataError:
                continue
            try:
                games_iter = list(iter_gamelog_games(data))
            except NBAGamelogSchemaError:
                invalid_schema += 1
                continue
            for st_display, meta, cat_event in games_iter:
                if "regular season" not in st_display.lower():
                    skipped_non_regular += 1
                    continue
                event_id = str(cat_event.get("eventId") or "").strip()
                if not event_id or event_id in seen:
                    continue
                try:
                    game_date = _clock(meta.get("gameDate"), "NBA_GAMELOG_DATE")
                except NBADataError:
                    invalid_schema += 1
                    continue
                if game_date >= now or game_date >= tipoff:
                    continue
                try:
                    stats = decode_nba_gamelog_event(data, cat_event)
                except (NBAGamelogSchemaError, ValueError, TypeError, KeyError):
                    invalid_schema += 1
                    continue
                # The gamelog page is per-athlete; the event's team entry
                # confirms which team the player represented that night, and
                # the home/away scores give that team's final total.
                team_entry = meta.get("team") or {}
                played_for = str(team_entry.get("id") or "").strip() if isinstance(team_entry, dict) else ""
                try:
                    if played_for and played_for == str(meta.get("homeTeamId") or ""):
                        team_points = int(str(meta.get("homeTeamScore")).strip())
                    elif played_for and played_for == str(meta.get("awayTeamId") or ""):
                        team_points = int(str(meta.get("awayTeamScore")).strip())
                    else:
                        team_points = None
                except (ValueError, TypeError, AttributeError):
                    team_points = None
                seen.add(event_id)
                hist.append((game_date, event_id, stats, played_for, team_points))

        hist.sort(key=lambda x: x[0], reverse=True)
        latest = hist[:max_games]
        if len(latest) < min_games:
            raise MissingNBAHistory(
                f"FEWER_THAN_{min_games}_VERIFIED_NAMED_PRIOR_GAMES:"
                f"found={len(latest)}")

        dates = [d.isoformat() for d, _, _, _, _ in latest]
        return {
            "game_id": str(game.get("id") or ""),
            "player_id": athlete_id,
            "player_name": athlete.get("displayName") or player_name,
            "player_team_id": athlete_team_id,
            "player_team_abbr": team_abbr.get(athlete_team_id, ""),
            "home_team": home_name,
            "away_team": away_name,
            "tipoff_utc": tipoff.isoformat(),
            "source_as_of_utc": now.isoformat(),
            "prior_game_times_utc": dates,
            "features": {"game_history": [
                {**stats, "played_for_team_id": played_for,
                 "team_points": team_points}
                for _, _, stats, played_for, team_points in latest
            ]},
            "explicit_stat_fields": sorted({k for _, _, s, _, _ in latest for k in s}),
            "schema_rejected_prior_events": invalid_schema,
            "skipped_non_regular_season_games": skipped_non_regular,
            "source_endpoint": f"gamelog(athlete_id={athlete_id})",
            "prior_game_count": len(latest),
        }


def to_box_observations(result: dict, *, observed_at: str):
    """Convert prior_games() output to NBAPlayerBoxObservation rows.

    Feeds sportsedge.sports.nba.player_history.fit_player_role for role
    fitting. Raises MissingNBAHistory when a required field is unverified.
    """
    from .player_history import NBAPlayerBoxObservation

    obs_at = _clock(observed_at, "NBA_OBSERVED_AT")
    rows = []
    game_id = result.get("game_id") or "unknown"
    player_id = result.get("player_id") or ""
    team_id = result.get("player_team_id") or ""
    if not player_id or not team_id:
        raise MissingNBAHistory("NBA_PLAYER_OBSERVATION_IDENTITY_UNVERIFIED")
    for game_time, stats in zip(result.get("prior_game_times_utc") or [],
                                result.get("features", {}).get("game_history") or []):
        try:
            tipoff = _clock(game_time, "NBA_PRIOR_TIPOFF")
            minutes = float(stats["minutes"])
            points = int(stats["points"])
            rebounds = int(stats["rebounds"])
            assists = int(stats["assists"])
            threes = int(stats["threes_made"])
            team_points = stats.get("team_points")
            team_points = int(team_points) if team_points is not None else points
            if team_points < points:
                raise MissingNBAHistory("NBA_PLAYER_OBSERVATION_TEAM_POINTS_INCONSISTENT")
        except (KeyError, ValueError, TypeError, NBADataError) as exc:
            raise MissingNBAHistory("NBA_PLAYER_OBSERVATION_STAT_UNVERIFIED") from exc
        row = NBAPlayerBoxObservation(
            game_id=game_id,
            player_id=player_id,
            team_id=team_id,
            tipoff=tipoff,
            observed_at=obs_at,
            minutes=minutes,
            points=points,
            rebounds=rebounds,
            assists=assists,
            threes=threes,
            team_points=team_points,
            source="espn_nba_gamelog_v3",
            source_version="2026-10-11",
        )
        rows.append(row)
    return rows
