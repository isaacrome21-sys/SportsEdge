"""Point-in-time CFB team metrics reconstructed from SportsDataverse game rows.

Every target snapshot is built strictly from completed games before ``through_week``.
Same-week and future rows are never eligible. The feature surface is market-blind.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

from .source import CFBTeamMetrics

HISTORICAL_FEATURE_CONTRACT = "CFB_HISTORICAL_PIT_FEATURE_V1"


class CFBHistoricalFeatureError(ValueError):
    pass


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise CFBHistoricalFeatureError(f"{name}:integer required")
    try:
        out = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise CFBHistoricalFeatureError(f"{name}:integer required") from exc
    return out


def _num(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBHistoricalFeatureError(f"{name}:numeric required") from exc
    if not isfinite(out):
        raise CFBHistoricalFeatureError(f"{name}:finite required")
    return out


def _bool(value: Any, name: str) -> bool:
    if type(value) is bool:
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "t", "1"}:
        return True
    if text in {"false", "f", "0"}:
        return False
    raise CFBHistoricalFeatureError(f"{name}:bool required")


def _game_id(row: Mapping[str, Any]) -> str:
    text = str(row.get("game_id") or "").strip()
    if not text:
        raise CFBHistoricalFeatureError("game_id required")
    return text


def _team_id(row: Mapping[str, Any], name: str = "pos_team") -> str:
    text = str(row.get(name) or "").strip()
    if not text:
        raise CFBHistoricalFeatureError(f"{name} required")
    return str(_int(text, name))


def _index(
    rows: Iterable[Mapping[str, Any]], *, eligible_games: set[str], label: str
) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise CFBHistoricalFeatureError(f"{label}:row object required")
        game = _game_id(raw)
        if game not in eligible_games:
            continue
        team = _team_id(raw)
        key = (game, team)
        if key in out:
            raise CFBHistoricalFeatureError(f"{label}:duplicate:{game}:{team}")
        out[key] = dict(raw)
    return out


def _schedule_games(
    rows: Iterable[Mapping[str, Any]], *, season: int, through_week: int
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, str]]:
    if through_week <= 0:
        raise CFBHistoricalFeatureError("through_week must be positive")
    games: dict[str, dict[str, Any]] = {}
    team_games: dict[str, list[str]] = defaultdict(list)
    names: dict[str, str] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise CFBHistoricalFeatureError("schedules:row object required")
        if _int(raw.get("season"), "schedule.season") != season:
            continue
        week = _int(raw.get("week"), "schedule.week")
        if week >= through_week:
            continue
        completed_raw = raw.get("status_type_completed", raw.get("completed"))
        if not _bool(completed_raw, "schedule.completed"):
            continue
        game = _game_id(raw)
        if game in games:
            raise CFBHistoricalFeatureError(f"schedules:duplicate:{game}")
        home = _team_id(raw, "home_id")
        away = _team_id(raw, "away_id")
        if home == away:
            raise CFBHistoricalFeatureError(f"schedules:same_team:{game}")
        home_name = str(raw.get("home_location") or raw.get("home_team") or "").strip()
        away_name = str(raw.get("away_location") or raw.get("away_team") or "").strip()
        if not home_name or not away_name:
            raise CFBHistoricalFeatureError(f"schedules:team_name_missing:{game}")
        games[game] = dict(raw)
        team_games[home].append(game)
        team_games[away].append(game)
        names[home], names[away] = home_name, away_name
    if not games:
        raise CFBHistoricalFeatureError("CFB_HISTORICAL_NO_PRIOR_COMPLETED_GAMES")
    return games, dict(team_games), names


def _pair(
    index: Mapping[tuple[str, str], Mapping[str, Any]], *, game: str, team: str,
    schedule: Mapping[str, Any], label: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    home = str(_int(schedule.get("home_id"), "home_id"))
    away = str(_int(schedule.get("away_id"), "away_id"))
    if team not in {home, away}:
        raise CFBHistoricalFeatureError(f"{label}:team_not_in_game:{game}:{team}")
    opponent = away if team == home else home
    own = index.get((game, team))
    opp = index.get((game, opponent))
    if own is None or opp is None:
        raise CFBHistoricalFeatureError(f"{label}:pair_missing:{game}:{team}")
    return own, opp


def _sum(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(_num(row.get(field), field) for row in rows)


def _ratio(numerator: float, denominator: float, name: str) -> float:
    if denominator <= 0:
        raise CFBHistoricalFeatureError(f"{name}:denominator must be positive")
    value = numerator / denominator
    if not isfinite(value):
        raise CFBHistoricalFeatureError(f"{name}:nonfinite")
    return value


def _pbp_eckel(
    rows: Iterable[Mapping[str, Any]], *, eligible_games: set[str]
) -> dict[str, dict[str, float]]:
    # Drive-level scoring-opportunity creation and points earned while the offense
    # retained possession. Defensive return scores are therefore not credited.
    eckel_drives: dict[str, set[tuple[str, str]]] = defaultdict(set)
    drive_points: dict[tuple[str, str, str], float] = defaultdict(float)
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise CFBHistoricalFeatureError("pbp:row object required")
        game = str(raw.get("game_id") or "").strip()
        if game not in eligible_games:
            continue
        team_raw = raw.get("start.pos_team.id", raw.get("pos_team"))
        drive = str(raw.get("drive.id") or raw.get("drive_id") or "").strip()
        if team_raw in (None, "") or not drive:
            continue
        team = str(_int(team_raw, "pbp.pos_team"))
        seen.add(team)
        if _bool(raw.get("scoring_opp", False), "pbp.scoring_opp"):
            eckel_drives[team].add((game, drive))

        home = str(raw.get("homeTeamId") or raw.get("home_id") or "").strip()
        away = str(raw.get("awayTeamId") or raw.get("away_id") or "").strip()
        if not home or not away:
            continue
        if team == str(_int(home, "pbp.homeTeamId")):
            before, after = raw.get("lag_homeScore"), raw.get("homeScore")
        elif team == str(_int(away, "pbp.awayTeamId")):
            before, after = raw.get("lag_awayScore"), raw.get("awayScore")
        else:
            raise CFBHistoricalFeatureError(f"pbp:possession_team_not_participant:{game}:{team}")
        if before in (None, "") or after in (None, ""):
            continue
        delta = _num(after, "pbp.score_after") - _num(before, "pbp.score_before")
        if delta > 0:
            drive_points[(team, game, drive)] += delta

    out: dict[str, dict[str, float]] = {}
    for team in seen:
        keys = eckel_drives.get(team, set())
        points = sum(drive_points.get((team, game, drive), 0.0) for game, drive in keys)
        out[team] = {"eckel_drives": float(len(keys)), "eckel_points": float(points)}
    return out


def build_week_to_date_metrics(
    *,
    season: int,
    through_week: int,
    schedules: Iterable[Mapping[str, Any]],
    adv_team: Iterable[Mapping[str, Any]],
    adv_situational: Iterable[Mapping[str, Any]],
    adv_drives: Iterable[Mapping[str, Any]],
    play_by_play: Iterable[Mapping[str, Any]],
    feature_asof_ts: str,
) -> dict[str, CFBTeamMetrics]:
    year = _int(season, "season")
    week = _int(through_week, "through_week")
    game_map, team_games, names = _schedule_games(schedules, season=year, through_week=week)
    eligible = set(game_map)
    team_idx = _index(adv_team, eligible_games=eligible, label="adv_team")
    situ_idx = _index(adv_situational, eligible_games=eligible, label="adv_situational")
    drives_idx = _index(adv_drives, eligible_games=eligible, label="adv_drives")
    eckel = _pbp_eckel(play_by_play, eligible_games=eligible)

    asof = str(feature_asof_ts or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(asof)
    except ValueError as exc:
        raise CFBHistoricalFeatureError("feature_asof_ts invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBHistoricalFeatureError("feature_asof_ts timezone required")
    asof = dt.astimezone(timezone.utc).isoformat()

    out: dict[str, CFBTeamMetrics] = {}
    for team, games in sorted(team_games.items()):
        own_team: list[Mapping[str, Any]] = []
        opp_team: list[Mapping[str, Any]] = []
        own_situ: list[Mapping[str, Any]] = []
        opp_situ: list[Mapping[str, Any]] = []
        own_drives: list[Mapping[str, Any]] = []
        opp_drives: list[Mapping[str, Any]] = []
        for game in games:
            schedule = game_map[game]
            own, opp = _pair(team_idx, game=game, team=team, schedule=schedule, label="adv_team")
            own_team.append(own); opp_team.append(opp)
            own, opp = _pair(situ_idx, game=game, team=team, schedule=schedule, label="adv_situational")
            own_situ.append(own); opp_situ.append(opp)
            own, opp = _pair(drives_idx, game=game, team=team, schedule=schedule, label="adv_drives")
            own_drives.append(own); opp_drives.append(opp)

        rushes = _sum(own_team, "rushes")
        passes = _sum(own_team, "passes")
        scrimmage = _sum(own_team, "scrimmage_plays")
        opp_rushes = _sum(opp_team, "rushes")
        opp_passes = _sum(opp_team, "passes")
        opp_scrimmage = _sum(opp_team, "scrimmage_plays")
        standard = _sum(own_situ, "standard_downs")
        passing_downs = _sum(own_situ, "passing_downs")
        drives = _sum(own_drives, "drives")
        opp_drives_n = _sum(opp_drives, "drives")
        e = eckel.get(team, {"eckel_drives": 0.0, "eckel_points": 0.0})
        if e["eckel_drives"] <= 0:
            raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_ECKEL_SAMPLE_MISSING:{team}")

        own_fp = _ratio(
            sum(_num(r.get("avg_field_position"), "avg_field_position") * _num(r.get("drives"), "drives") for r in own_drives),
            drives, "own_field_position",
        )
        opp_fp = _ratio(
            sum(_num(r.get("avg_field_position"), "avg_field_position") * _num(r.get("drives"), "drives") for r in opp_drives),
            opp_drives_n, "opp_field_position",
        )
        scoreboard_points = 0.0
        for game in games:
            s = game_map[game]
            home = str(_int(s.get("home_id"), "home_id"))
            score_field = "home_score" if team == home else "away_score"
            scoreboard_points += _num(s.get(score_field), score_field)

        out[names[team]] = CFBTeamMetrics(
            team=names[team], season=year, through_week=week - 1,
            sample_source="SPORTSDATAVERSE_WEEK_TO_DATE_V1",
            off_ppa_rush=_ratio(_sum(own_team, "EPA_rushing_overall"), rushes, "off_ppa_rush"),
            off_ppa_dropback=_ratio(_sum(own_team, "EPA_passing_overall"), passes, "off_ppa_dropback"),
            def_ppa_rush_allowed=_ratio(_sum(opp_team, "EPA_rushing_overall"), opp_rushes, "def_ppa_rush_allowed"),
            def_ppa_dropback_allowed=_ratio(_sum(opp_team, "EPA_passing_overall"), opp_passes, "def_ppa_dropback_allowed"),
            off_success_rate=_ratio(_sum(own_situ, "EPA_success"), scrimmage, "off_success_rate"),
            def_success_rate_allowed=_ratio(_sum(opp_situ, "EPA_success"), opp_scrimmage, "def_success_rate_allowed"),
            standard_down_ppa=_ratio(_sum(own_situ, "EPA_standard_down"), standard, "standard_down_ppa"),
            passing_down_success_rate=_ratio(_sum(own_situ, "EPA_success_passing_down"), passing_downs, "passing_down_success_rate"),
            eckel_rate=_ratio(e["eckel_drives"], drives, "eckel_rate"),
            points_per_eckel=_ratio(e["eckel_points"], e["eckel_drives"], "points_per_eckel"),
            points_per_drive=_ratio(scoreboard_points, drives, "points_per_drive"),
            net_field_position=opp_fp - own_fp,
            explosive_rate=_ratio(
                _sum(own_team, "EPA_explosive_rushing") + _sum(own_team, "EPA_explosive_passing"),
                rushes + passes, "explosive_rate",
            ),
            feature_asof_ts=asof,
            source_contract=HISTORICAL_FEATURE_CONTRACT,
        )
    return out
