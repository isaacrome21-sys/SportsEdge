"""Point-in-time historical feature producer for the production NFL M2.

This module converts frozen schedule, play-by-play, participation, depth-chart,
and stadium metadata into the exact market-blind feature dictionaries consumed
by :mod:`sportsedge.sports.nfl.m2`.

Evidence rules are intentionally strict:
- the current game's PBP never enters its own feature state;
- pressure comes from participation ``was_pressure``, never a sack proxy;
- starter QB identity comes from the depth-chart source, not the game's realized
  passer distribution;
- prior decay is fit using earlier seasons only;
- sportsbook fields remain top-level evaluation metadata and are never passed to
  the M2 feature builder;
- neutral-site geography fails closed unless an explicit venue contract is added.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from sportsedge.core.prior_decay import fit_weekly_prior_decay
from sportsedge.sports.nfl.m2 import build_nfl_m2_features

_EASTERN = ZoneInfo("America/New_York")
_EXPLOSIVE_YARDS = 20.0


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "yes", "y"}:
        return True
    if text in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _iso_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("NFL_M2_HISTORY_NAIVE_TIMESTAMP")
    return dt


def _game_start(row: Mapping[str, Any]) -> datetime:
    explicit = row.get("game_start_ts")
    if explicit not in (None, ""):
        return _iso_dt(explicit)
    gameday = str(row.get("gameday") or row.get("game_date") or "").strip()
    gametime = str(row.get("gametime") or "").strip()
    if not gameday or not gametime:
        raise ValueError("NFL_GAME_START_MISSING")
    day = date.fromisoformat(gameday)
    clock = time.fromisoformat(gametime)
    return datetime.combine(day, clock, tzinfo=_EASTERN)


def _game_sort_key(row: Mapping[str, Any]) -> tuple[datetime, str]:
    return _game_start(row), str(row.get("game_id") or "")


@dataclass
class _Stats:
    off_epa_sum: float = 0.0
    off_plays: int = 0
    def_epa_sum: float = 0.0
    def_plays: int = 0
    pass_epa_sum: float = 0.0
    pass_plays: int = 0
    rush_epa_sum: float = 0.0
    rush_plays: int = 0
    success: int = 0
    explosive: int = 0
    pressure_allowed: int = 0
    pressure_allowed_n: int = 0
    pressure_for: int = 0
    pressure_for_n: int = 0

    def add(self, other: "_Stats") -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def off_epa(self) -> float:
        return self.off_epa_sum / self.off_plays if self.off_plays else 0.0

    def def_epa(self) -> float:
        return self.def_epa_sum / self.def_plays if self.def_plays else 0.0

    def pass_epa(self) -> float:
        return self.pass_epa_sum / self.pass_plays if self.pass_plays else 0.0

    def rush_epa(self) -> float:
        return self.rush_epa_sum / self.rush_plays if self.rush_plays else 0.0

    def success_rate(self) -> float:
        return self.success / self.off_plays if self.off_plays else 0.0

    def explosive_rate(self) -> float:
        return self.explosive / self.off_plays if self.off_plays else 0.0

    def pressure_allowed_rate(self) -> float:
        return self.pressure_allowed / self.pressure_allowed_n if self.pressure_allowed_n else 0.0

    def pressure_for_rate(self) -> float:
        return self.pressure_for / self.pressure_for_n if self.pressure_for_n else 0.0


@dataclass
class _QBStats:
    epa_sum: float = 0.0
    dropbacks: int = 0

    def add(self, epa: float) -> None:
        self.epa_sum += float(epa)
        self.dropbacks += 1

    def mean(self) -> float:
        return self.epa_sum / self.dropbacks if self.dropbacks else 0.0


def _is_pass(row: Mapping[str, Any]) -> bool:
    flag = _bool(row.get("pass"))
    if flag is not None:
        return flag
    return str(row.get("play_type") or "").strip().lower() in {"pass", "qb_kneel", "qb_spike"}


def _is_rush(row: Mapping[str, Any]) -> bool:
    flag = _bool(row.get("rush"))
    if flag is not None:
        return flag
    return str(row.get("play_type") or "").strip().lower() == "run"


def _participation_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, int], bool]:
    index: dict[tuple[str, int], bool] = {}
    for raw in rows:
        gid = str(raw.get("nflverse_game_id") or raw.get("game_id") or "").strip()
        play_id = _int(raw.get("play_id"))
        pressure = _bool(raw.get("was_pressure"))
        if not gid or play_id is None or pressure is None:
            continue
        key = (gid, play_id)
        if key in index and index[key] != pressure:
            raise ValueError(f"NFL_PARTICIPATION_PRESSURE_CONFLICT:{gid}:{play_id}")
        index[key] = pressure
    return index


def _aggregate_games(
    pbp_rows: Iterable[Mapping[str, Any]],
    participation_rows: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[tuple[str, str], _Stats], dict[tuple[str, str], _QBStats]]:
    pressure = _participation_index(participation_rows)
    teams: dict[tuple[str, str], _Stats] = {}
    qbs: dict[tuple[str, str], _QBStats] = {}

    for raw in pbp_rows:
        gid = str(raw.get("game_id") or raw.get("nflverse_game_id") or "").strip()
        posteam = str(raw.get("posteam") or raw.get("possession_team") or "").strip()
        defteam = str(raw.get("defteam") or "").strip()
        play_id = _int(raw.get("play_id"))
        epa = _float(raw.get("epa"))
        if not gid or not posteam or not defteam or epa is None:
            continue

        offense = teams.setdefault((gid, posteam), _Stats())
        defense = teams.setdefault((gid, defteam), _Stats())
        offense.off_epa_sum += epa
        offense.off_plays += 1
        defense.def_epa_sum += epa
        defense.def_plays += 1

        is_pass = _is_pass(raw)
        is_rush = _is_rush(raw)
        if is_pass:
            offense.pass_epa_sum += epa
            offense.pass_plays += 1
        if is_rush:
            offense.rush_epa_sum += epa
            offense.rush_plays += 1
        offense.success += int(epa > 0.0)
        yards = _float(raw.get("yards_gained"))
        offense.explosive += int(yards is not None and yards >= _EXPLOSIVE_YARDS)

        dropback = _bool(raw.get("qb_dropback")) is True
        if dropback and play_id is not None and (gid, play_id) in pressure:
            was_pressure = pressure[(gid, play_id)]
            offense.pressure_allowed_n += 1
            offense.pressure_allowed += int(was_pressure)
            defense.pressure_for_n += 1
            defense.pressure_for += int(was_pressure)

        passer = str(raw.get("passer_player_id") or raw.get("passer_id") or "").strip()
        if dropback and passer:
            qb_epa = _float(raw.get("qb_epa"))
            if qb_epa is None:
                qb_epa = epa
            qbs.setdefault((gid, passer), _QBStats()).add(qb_epa)

    return teams, qbs


def _rank_one(value: Any) -> bool:
    rank = _int(value)
    return rank == 1


def select_starting_qb(
    depth_rows: Iterable[Mapping[str, Any]],
    *,
    team: str,
    season: int,
    week: int,
    game_start_ts: str | datetime,
) -> str:
    """Select starter QB from historical weekly or 2025+ timestamped charts."""
    rows = [dict(row) for row in depth_rows]
    start = _iso_dt(game_start_ts)
    team = str(team).strip()

    timestamped: list[tuple[datetime, str]] = []
    for row in rows:
        if row.get("dt") in (None, ""):
            continue
        row_team = str(row.get("team") or row.get("club_code") or "").strip()
        position = str(row.get("pos_abb") or row.get("position") or row.get("depth_position") or "").upper()
        if row_team != team or position != "QB" or not _rank_one(row.get("pos_rank")):
            continue
        dt = _iso_dt(row["dt"])
        player = str(row.get("gsis_id") or "").strip()
        if dt < start and player:
            timestamped.append((dt, player))
    if timestamped:
        latest = max(dt for dt, _ in timestamped)
        players = sorted({player for dt, player in timestamped if dt == latest})
        if len(players) != 1:
            raise ValueError(f"NFL_STARTING_QB_AMBIGUOUS:{team}:{season}:{week}")
        return players[0]

    weekly: list[tuple[int, str]] = []
    for row in rows:
        row_season = _int(row.get("season"))
        row_week = _int(row.get("week"))
        row_team = str(row.get("club_code") or row.get("team") or "").strip()
        position = str(row.get("depth_position") or row.get("position") or "").upper()
        depth_rank = row.get("depth_team", row.get("pos_rank"))
        if row_season != int(season) or row_week is None or row_week > int(week):
            continue
        if row_team != team or position != "QB" or not _rank_one(depth_rank):
            continue
        if str(row.get("game_type") or "REG").upper() not in {"REG", ""}:
            continue
        player = str(row.get("gsis_id") or "").strip()
        if player:
            weekly.append((row_week, player))
    if not weekly:
        raise ValueError(f"NFL_STARTING_QB_MISSING:{team}:{season}:{week}")
    latest_week = max(row_week for row_week, _ in weekly)
    players = sorted({player for row_week, player in weekly if row_week == latest_week})
    if len(players) != 1:
        raise ValueError(f"NFL_STARTING_QB_AMBIGUOUS:{team}:{season}:{week}")
    return players[0]


def _season_game_team_epa(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], float], dict[tuple[int, str], float]]:
    game_stats, _ = _aggregate_games(pbp_rows)
    per_game: dict[tuple[str, str], float] = {}
    totals: dict[tuple[int, str], tuple[float, int]] = {}
    for game in schedule_rows:
        gid = str(game.get("game_id") or "")
        season = _int(game.get("season"))
        if season is None:
            continue
        for team_key in ("home_team", "away_team"):
            team = str(game.get(team_key) or "").strip()
            stats = game_stats.get((gid, team))
            if not team or stats is None or stats.off_plays <= 0:
                continue
            value = stats.off_epa()
            per_game[(gid, team)] = value
            total, n = totals.get((season, team), (0.0, 0))
            totals[(season, team)] = (total + value, n + 1)
    final = {key: total / n for key, (total, n) in totals.items() if n}
    return per_game, final


def fit_nfl_prior_decay_curves(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
    *,
    min_train_seasons: int = 2,
    weeks: Iterable[int] = range(1, 7),
    grid_step: float = 0.05,
) -> dict[int, dict[int, float]]:
    """Fit week-specific prior weights for each held-out season using earlier seasons only."""
    if min_train_seasons < 1:
        raise ValueError("NFL_PRIOR_DECAY_MIN_TRAIN_SEASONS_INVALID")
    schedule = [dict(row) for row in schedule_rows if str(row.get("game_type") or "REG").upper() == "REG"]
    schedule.sort(key=_game_sort_key)
    per_game, final = _season_game_team_epa(schedule, pbp_rows)
    requested_weeks = tuple(int(week) for week in weeks)
    seasons = sorted({int(row["season"]) for row in schedule if row.get("season") not in (None, "")})

    # Build leakage-safe training examples within each historical season: the
    # current predictor is season-to-date before the game; the prior predictor is
    # the previous season final mean; target is this training game's realized EPA.
    examples: list[dict[str, Any]] = []
    current: dict[tuple[int, str], tuple[float, int]] = {}
    for game in schedule:
        season = int(game["season"])
        week = int(game["week"])
        gid = str(game["game_id"])
        for team_key in ("home_team", "away_team"):
            team = str(game[team_key])
            target = per_game.get((gid, team))
            prior = final.get((season - 1, team))
            if target is None:
                continue
            total, n = current.get((season, team), (0.0, 0))
            current_pred = total / n if n else 0.0
            if prior is not None:
                examples.append({
                    "season": season,
                    "week": week,
                    "target": target,
                    "prior_pred": prior,
                    "current_pred": current_pred,
                })
            current[(season, team)] = (total + target, n + 1)

    curves: dict[int, dict[int, float]] = {}
    for test_season in seasons:
        train_seasons = [season for season in seasons if season < test_season]
        if len(train_seasons) < min_train_seasons:
            continue
        train = [row for row in examples if int(row["season"]) < test_season and int(row["week"]) in requested_weeks]
        for week in requested_weeks:
            if not any(int(row["week"]) == week for row in train):
                raise ValueError(f"NFL_PRIOR_DECAY_TRAINING_WEEK_MISSING:{test_season}:{week}")
        curves[test_season] = fit_weekly_prior_decay(train, weeks=requested_weeks, grid_step=grid_step)
    return curves


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _stadium_for_team(rows: Iterable[Mapping[str, Any]], *, team: str, gameday: date) -> dict[str, Any]:
    candidates: list[tuple[date, dict[str, Any]]] = []
    for raw in rows:
        row = dict(raw)
        row_team = str(row.get("team_fastr") or row.get("team") or "").strip()
        if row_team != team:
            continue
        first = _date(row.get("first_game_date")) or date.min
        last = _date(row.get("last_game_date")) or date.max
        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        tz = _float(row.get("tz_offset"))
        if first <= gameday <= last and lat is not None and lon is not None and tz is not None:
            candidates.append((first, row))
    if not candidates:
        raise ValueError(f"NFL_STADIUM_MAPPING_MISSING:{team}:{gameday.isoformat()}")
    latest_first = max(first for first, _ in candidates)
    selected = [row for first, row in candidates if first == latest_first]
    if len(selected) != 1:
        raise ValueError(f"NFL_STADIUM_MAPPING_AMBIGUOUS:{team}:{gameday.isoformat()}")
    return selected[0]


def _haversine_miles(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    lat1 = radians(float(a["lat"]))
    lon1 = radians(float(a["lon"]))
    lat2 = radians(float(b["lat"]))
    lon2 = radians(float(b["lon"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2.0) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2.0) ** 2
    return 3958.7613 * 2.0 * asin(min(1.0, sqrt(h)))


def _season_stats_mean(state: Mapping[tuple[int, str], _Stats], season: int, team: str) -> _Stats:
    return state.get((season, team), _Stats())


def _prior_weight(curves: Mapping[int, Mapping[int, float]], *, season: int, week: int) -> float:
    if season not in curves:
        raise ValueError(f"NFL_PRIOR_DECAY_CURVE_MISSING:{season}")
    curve = curves[season]
    if week in curve:
        value = float(curve[week])
    elif curve and week > max(int(key) for key in curve):
        value = 0.0
    else:
        raise ValueError(f"NFL_PRIOR_DECAY_WEEK_MISSING:{season}:{week}")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"NFL_PRIOR_DECAY_WEIGHT_INVALID:{season}:{week}")
    return value


def _previous_season_off_epa(
    completed: Mapping[tuple[int, str], _Stats],
    *,
    season: int,
    team: str,
) -> float:
    return completed.get((season - 1, team), _Stats()).off_epa()


def _qb_adjustment(qb: str, qb_state: Mapping[str, _QBStats], league_qb: _QBStats) -> float:
    player = qb_state.get(qb)
    if player is None or player.dropbacks <= 0 or league_qb.dropbacks <= 0:
        return 0.0
    return player.mean() - league_qb.mean()


def build_nfl_m2_history_rows(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
    participation_rows: Iterable[Mapping[str, Any]],
    depth_rows: Iterable[Mapping[str, Any]],
    stadium_rows: Iterable[Mapping[str, Any]],
    *,
    prior_decay_curves: Mapping[int, Mapping[int, float]],
) -> list[dict[str, Any]]:
    """Build exact production-M2 historical rows from strictly prior state."""
    schedule = [dict(row) for row in schedule_rows if str(row.get("game_type") or "REG").upper() == "REG"]
    schedule.sort(key=_game_sort_key)
    depth = [dict(row) for row in depth_rows]
    stadiums = [dict(row) for row in stadium_rows]
    game_stats, game_qbs = _aggregate_games(pbp_rows, participation_rows)

    season_state: dict[tuple[int, str], _Stats] = {}
    completed_season_state: dict[tuple[int, str], _Stats] = {}
    qb_state: dict[str, _QBStats] = {}
    league_qb = _QBStats()
    out: list[dict[str, Any]] = []

    active_season: int | None = None
    for game in schedule:
        season = int(game["season"])
        week = int(game["week"])
        gid = str(game.get("game_id") or "").strip()
        home = str(game.get("home_team") or "").strip()
        away = str(game.get("away_team") or "").strip()
        if not gid or not home or not away:
            raise ValueError("NFL_HISTORY_GAME_IDENTITY_MISSING")

        if active_season is None:
            active_season = season
        elif season != active_season:
            # Freeze the just-completed season before any feature in the next
            # season is constructed.
            for (state_season, team), stats in season_state.items():
                if state_season == active_season:
                    completed_season_state[(state_season, team)] = stats
            active_season = season

        start = _game_start(game)
        gameday = start.date()
        if str(game.get("location") or "Home").strip().lower() != "home":
            raise ValueError(f"NFL_NEUTRAL_VENUE_UNRESOLVED:{gid}")
        home_venue = _stadium_for_team(stadiums, team=home, gameday=gameday)
        away_origin = _stadium_for_team(stadiums, team=away, gameday=gameday)

        # Curves do not exist for initial burn-in seasons. Those games still
        # update all states but are not eligible production-M2 evaluation rows.
        curve_available = season in prior_decay_curves
        if curve_available:
            weight = _prior_weight(prior_decay_curves, season=season, week=week)
            home_qb = select_starting_qb(depth, team=home, season=season, week=week, game_start_ts=start)
            away_qb = select_starting_qb(depth, team=away, season=season, week=week, game_start_ts=start)

            home_stats = _season_stats_mean(season_state, season, home)
            away_stats = _season_stats_mean(season_state, season, away)
            cutoff = (start - timedelta(microseconds=1)).isoformat()
            home_rest = _float(game.get("home_rest")) or 0.0
            away_rest = _float(game.get("away_rest")) or 0.0
            wind = _float(game.get("wind_mph"))
            if wind is None:
                wind = _float(game.get("wind")) or 0.0
            roof = str(game.get("roof") or "").strip().lower()
            roof_closed = 1.0 if roof in {"closed", "dome"} else 0.0
            away_miles = _haversine_miles(away_origin, home_venue)
            away_tz = abs(float(away_origin["tz_offset"]) - float(home_venue["tz_offset"]))

            common_home = {
                "feature_asof_ts": cutoff,
                "game_start_ts": start.isoformat(),
                "off_epa": home_stats.off_epa(),
                "def_epa": home_stats.def_epa(),
                "pass_epa": home_stats.pass_epa(),
                "rush_epa": home_stats.rush_epa(),
                "opp_off_epa": away_stats.off_epa(),
                "opp_def_epa": away_stats.def_epa(),
                "pressure_for": home_stats.pressure_for_rate(),
                "pressure_allowed": home_stats.pressure_allowed_rate(),
                "success_rate": home_stats.success_rate(),
                "explosive_rate": home_stats.explosive_rate(),
                "rest_diff_days": home_rest - away_rest,
                "travel_miles": 0.0,
                "timezone_crossings": 0.0,
                "short_week": float(home_rest < 6.0),
                "bye_week": float(home_rest >= 10.0),
                "wind_mph": wind,
                "roof_closed": roof_closed,
                "qb_id": home_qb,
                "qb_adjustment": _qb_adjustment(home_qb, qb_state, league_qb),
                "prior_efficiency": weight * _previous_season_off_epa(
                    completed_season_state, season=season, team=home
                ),
                "prior_weight": weight,
            }
            common_away = {
                "feature_asof_ts": cutoff,
                "game_start_ts": start.isoformat(),
                "off_epa": away_stats.off_epa(),
                "def_epa": away_stats.def_epa(),
                "pass_epa": away_stats.pass_epa(),
                "rush_epa": away_stats.rush_epa(),
                "opp_off_epa": home_stats.off_epa(),
                "opp_def_epa": home_stats.def_epa(),
                "pressure_for": away_stats.pressure_for_rate(),
                "pressure_allowed": away_stats.pressure_allowed_rate(),
                "success_rate": away_stats.success_rate(),
                "explosive_rate": away_stats.explosive_rate(),
                "rest_diff_days": away_rest - home_rest,
                "travel_miles": away_miles,
                "timezone_crossings": away_tz,
                "short_week": float(away_rest < 6.0),
                "bye_week": float(away_rest >= 10.0),
                "wind_mph": wind,
                "roof_closed": roof_closed,
                "qb_id": away_qb,
                "qb_adjustment": _qb_adjustment(away_qb, qb_state, league_qb),
                "prior_efficiency": weight * _previous_season_off_epa(
                    completed_season_state, season=season, team=away
                ),
                "prior_weight": weight,
            }

            home_features = build_nfl_m2_features(common_home)
            away_features = build_nfl_m2_features(common_away)
            out.append({
                "game_id": gid,
                "season": season,
                "week": week,
                "game_start_ts": start.isoformat(),
                "home_team": home,
                "away_team": away,
                "home_score": _float(game.get("home_score")),
                "away_score": _float(game.get("away_score")),
                "home_features": home_features,
                "away_features": away_features,
                # Market data is retained only at this evaluation layer.
                "spread_line": _float(game.get("spread_line")),
                "home_spread_odds": _float(game.get("home_spread_odds")),
                "away_spread_odds": _float(game.get("away_spread_odds")),
                "total_line": _float(game.get("total_line")),
                "over_odds": _float(game.get("over_odds")),
                "under_odds": _float(game.get("under_odds")),
                "feature_provenance": {
                    "pbp": "NFLVERSE_PBP_STRICTLY_PRIOR_GAME_STATE",
                    "pressure": "NFLVERSE_PARTICIPATION_WAS_PRESSURE",
                    "starter_qb": "NFLVERSE_DEPTH_CHART",
                    "travel": "DATE_BOUND_TEAM_STADIUM_METADATA",
                    "prior_decay": "EARLIER_SEASONS_ONLY_FIT",
                    "explosive_yards_threshold": _EXPLOSIVE_YARDS,
                },
            })

        # Only after the current feature row exists may this game's realized
        # information enter future state.
        for team in (home, away):
            stats = game_stats.get((gid, team))
            if stats is not None:
                season_state.setdefault((season, team), _Stats()).add(stats)
        for (game_id, qb), stats in game_qbs.items():
            if game_id != gid:
                continue
            state = qb_state.setdefault(qb, _QBStats())
            state.epa_sum += stats.epa_sum
            state.dropbacks += stats.dropbacks
            league_qb.epa_sum += stats.epa_sum
            league_qb.dropbacks += stats.dropbacks

    # Preserve the final season state for completeness; it never feeds an
    # already-built row and therefore cannot create same-season look-ahead.
    if active_season is not None:
        for (state_season, team), stats in season_state.items():
            if state_season == active_season:
                completed_season_state[(state_season, team)] = stats
    return out
