from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .mlb_v7_final_timecode import archived_final_feed_rows
from .mlb_v7_statsapi_history import MLBV7StatsAPIHistoryError
from .mlb_v7_travel_history import timecode_to_utc_iso


class MLBV7RawSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BullpenUsageRow:
    game_id: int
    team_id: int
    pitcher_id: int
    pitches: int
    game_start_time: str
    final_at: str


@dataclass(frozen=True)
class ParkRawRow:
    season: int
    venue_id: int
    runs: int
    plate_appearances: int
    home_runs: int
    batter_stand: str
    game_id: int
    play_index: int
    game_start_time: str
    final_at: str


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise MLBV7RawSourceError(f"{field}_INVALID")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBV7RawSourceError(f"{field}_INVALID") from exc
    if out <= 0:
        raise MLBV7RawSourceError(f"{field}_INVALID")
    return out


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise MLBV7RawSourceError(f"{field}_INVALID")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBV7RawSourceError(f"{field}_INVALID") from exc
    if out < 0:
        raise MLBV7RawSourceError(f"{field}_INVALID")
    return out


def _utc_iso(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MLBV7RawSourceError(f"{field}_MISSING")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBV7RawSourceError(f"{field}_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBV7RawSourceError(f"{field}_NOT_TIMEZONE_AWARE")
    return dt.astimezone(timezone.utc).isoformat()


def archived_feed_identity(feed: Mapping[str, Any]) -> tuple[int, int, int, int, str, str]:
    try:
        game_id = _positive_int(feed.get("gamePk"), "GAME_ID")
        game_data = feed["gameData"]
        away_id = _positive_int(game_data["teams"]["away"]["id"], "AWAY_TEAM_ID")
        home_id = _positive_int(game_data["teams"]["home"]["id"], "HOME_TEAM_ID")
        venue_id = _positive_int(game_data["venue"]["id"], "VENUE_ID")
        game_start_time = _utc_iso(game_data["datetime"]["dateTime"], "GAME_START_TIME")
        season = str(game_data["game"]["season"])
    except (KeyError, TypeError) as exc:
        raise MLBV7RawSourceError("ARCHIVED_FEED_IDENTITY_INCOMPLETE") from exc
    if not season.isdigit() or len(season) != 4:
        raise MLBV7RawSourceError("SEASON_INVALID")
    return game_id, away_id, home_id, venue_id, game_start_time, season


def _trusted_final_at(feed: Mapping[str, Any]) -> str:
    game_id, away_id, home_id, venue_id, game_start, _ = archived_feed_identity(feed)
    game = {
        "game_id": game_id,
        "away_team_id": away_id,
        "home_team_id": home_id,
        "venue_id": venue_id,
        "game_start_time": game_start,
        "status": "Final",
        "official_date": str(((feed.get("gameData") or {}).get("datetime") or {}).get("officialDate") or game_start[:10]),
        "game_type": str(((feed.get("gameData") or {}).get("game") or {}).get("type") or "R"),
    }
    try:
        rows, _ = archived_final_feed_rows(game, feed)
    except MLBV7StatsAPIHistoryError as exc:
        raise MLBV7RawSourceError(str(exc)) from exc
    return rows[0].final_at


def bullpen_usage_rows(feed: Mapping[str, Any]) -> list[BullpenUsageRow]:
    game_id, away_id, home_id, _, game_start, _ = archived_feed_identity(feed)
    final_at = _trusted_final_at(feed)
    if datetime.fromisoformat(final_at) < datetime.fromisoformat(game_start):
        raise MLBV7RawSourceError("FINAL_AT_BEFORE_GAME_START")
    try:
        box_teams = feed["liveData"]["boxscore"]["teams"]
    except (KeyError, TypeError) as exc:
        raise MLBV7RawSourceError("BOXSCORE_TEAMS_MISSING") from exc

    out: list[BullpenUsageRow] = []
    for side, expected_team_id in (("away", away_id), ("home", home_id)):
        team_box = box_teams.get(side) if isinstance(box_teams, Mapping) else None
        if not isinstance(team_box, Mapping):
            raise MLBV7RawSourceError(f"BOXSCORE_TEAM_MISSING:{side}")
        actual_team_id = _positive_int((team_box.get("team") or {}).get("id"), f"{side.upper()}_BOXSCORE_TEAM_ID")
        if actual_team_id != expected_team_id:
            raise MLBV7RawSourceError(f"BOXSCORE_TEAM_ID_MISMATCH:{side}")
        pitchers = team_box.get("pitchers")
        players = team_box.get("players")
        if not isinstance(pitchers, list) or not pitchers or not isinstance(players, Mapping):
            raise MLBV7RawSourceError(f"PITCHER_LIST_INVALID:{side}")
        pitcher_ids = [_positive_int(pid, "PITCHER_ID") for pid in pitchers]
        if len(pitcher_ids) != len(set(pitcher_ids)):
            raise MLBV7RawSourceError(f"PITCHER_LIST_DUPLICATE:{side}")
        starters: list[int] = []
        parsed: list[tuple[int, int, int]] = []
        for pitcher_id in pitcher_ids:
            player = players.get(f"ID{pitcher_id}")
            if not isinstance(player, Mapping):
                raise MLBV7RawSourceError(f"PITCHER_PLAYER_MISSING:{pitcher_id}")
            pitching = ((player.get("stats") or {}).get("pitching") or {})
            if not isinstance(pitching, Mapping):
                raise MLBV7RawSourceError(f"PITCHING_STATS_MISSING:{pitcher_id}")
            games_started = _nonnegative_int(pitching.get("gamesStarted", 0), "GAMES_STARTED")
            games_pitched = _nonnegative_int(pitching.get("gamesPitched", 0), "GAMES_PITCHED")
            pitches = _nonnegative_int(pitching.get("numberOfPitches"), "NUMBER_OF_PITCHES")
            alt = pitching.get("pitchesThrown")
            if alt is not None and _nonnegative_int(alt, "PITCHES_THROWN") != pitches:
                raise MLBV7RawSourceError(f"PITCH_COUNT_MISMATCH:{pitcher_id}")
            if games_started > 0:
                starters.append(pitcher_id)
            parsed.append((pitcher_id, games_started, games_pitched))
        if len(starters) != 1:
            raise MLBV7RawSourceError(f"STARTER_CARDINALITY_INVALID:{side}:{len(starters)}")
        for pitcher_id, games_started, games_pitched in parsed:
            if games_started:
                continue
            if games_pitched <= 0:
                raise MLBV7RawSourceError(f"RELIEVER_GAMES_PITCHED_INVALID:{pitcher_id}")
            pitching = ((players[f"ID{pitcher_id}"].get("stats") or {}).get("pitching") or {})
            pitches = _nonnegative_int(pitching.get("numberOfPitches"), "NUMBER_OF_PITCHES")
            out.append(BullpenUsageRow(
                game_id=game_id,
                team_id=expected_team_id,
                pitcher_id=pitcher_id,
                pitches=pitches,
                game_start_time=game_start,
                final_at=final_at,
            ))
    out.sort(key=lambda row: (row.team_id, row.pitcher_id))
    return out


def park_raw_rows(feed: Mapping[str, Any]) -> list[ParkRawRow]:
    game_id, _, _, venue_id, game_start, season_text = archived_feed_identity(feed)
    final_at = _trusted_final_at(feed)
    season = int(season_text)
    try:
        live_data = feed["liveData"]
        plays = live_data["plays"]["allPlays"]
        line_teams = live_data["linescore"]["teams"]
    except (KeyError, TypeError) as exc:
        raise MLBV7RawSourceError("PLAY_OR_LINESCORE_DATA_MISSING") from exc
    if not isinstance(plays, list) or not plays:
        raise MLBV7RawSourceError("ALL_PLAYS_MISSING")
    if not isinstance(line_teams, Mapping):
        raise MLBV7RawSourceError("LINESCORE_TEAMS_MISSING")

    prev_away = 0
    prev_home = 0
    out: list[ParkRawRow] = []
    for index, play in enumerate(plays):
        if not isinstance(play, Mapping):
            raise MLBV7RawSourceError(f"PLAY_INVALID:{index}")
        result = play.get("result") or {}
        matchup = play.get("matchup") or {}
        bat_side = (matchup.get("batSide") or {}).get("code")
        if bat_side not in {"L", "R"}:
            raise MLBV7RawSourceError(f"BATTER_STAND_INVALID:{index}:{bat_side}")
        away_score = _nonnegative_int(result.get("awayScore"), "AWAY_SCORE")
        home_score = _nonnegative_int(result.get("homeScore"), "HOME_SCORE")
        if away_score < prev_away or home_score < prev_home:
            raise MLBV7RawSourceError(f"SCORE_REGRESSION:{index}")
        runs = (away_score - prev_away) + (home_score - prev_home)
        event_type = str(result.get("eventType") or "")
        out.append(ParkRawRow(
            season=season,
            venue_id=venue_id,
            runs=runs,
            plate_appearances=1,
            home_runs=1 if event_type == "home_run" else 0,
            batter_stand=bat_side,
            game_id=game_id,
            play_index=index,
            game_start_time=game_start,
            final_at=final_at,
        ))
        prev_away, prev_home = away_score, home_score

    expected_away = _nonnegative_int(((line_teams.get("away") or {}).get("runs")), "FINAL_AWAY_RUNS")
    expected_home = _nonnegative_int(((line_teams.get("home") or {}).get("runs")), "FINAL_HOME_RUNS")
    if (prev_away, prev_home) != (expected_away, expected_home):
        raise MLBV7RawSourceError("FINAL_SCORE_RECONCILIATION_FAILED")
    if sum(row.runs for row in out) != expected_away + expected_home:
        raise MLBV7RawSourceError("RUN_TOTAL_RECONCILIATION_FAILED")
    return out
