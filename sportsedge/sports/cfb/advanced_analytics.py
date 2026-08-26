"""Auditable CFB advanced-metric aggregation from prior play-by-play.

This module calculates SportsEdge-owned football features from canonical PBP rows.
It does not ingest sportsbook data and does not consume third-party win probabilities
or projected scores.

Operational contracts:
- garbage-time plays are excluded when the source marks them;
- EPA is consumed only from a source field explicitly named ``EPA``/``epa``;
- an Eckel/scoring-opportunity drive reaches the opponent 40 or scores;
- explosive plays are rush >= 10 yards or pass >= 20 yards;
- late-down conversion is a 3rd/4th-down play gaining at least the distance-to-go.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Iterable, Mapping

ADVANCED_FEATURE_CONTRACT = "CFB_ADVANCED_PBP_V1"
ECKEL_RULE_VERSION = "OPP_40_OR_SCORE_V1"
EXPLOSIVE_RULE_VERSION = "RUSH10_PASS20_V1"


class CFBAdvancedMetricError(ValueError):
    pass


@dataclass(frozen=True)
class CFBTeamAdvancedMetrics:
    team: str
    sample_games: int
    offensive_plays: int
    defensive_plays: int
    drives: int
    off_epa_rush: float
    off_epa_dropback: float
    def_epa_rush_allowed: float
    def_epa_dropback_allowed: float
    off_success_rate: float
    off_rush_success_rate: float
    off_dropback_success_rate: float
    def_success_rate_allowed: float
    early_down_epa: float
    late_down_conversion_rate: float
    eckel_rate: float
    points_per_eckel: float
    points_per_drive: float
    net_field_position: float
    explosive_rate: float
    feature_asof_ts: str
    contract: str = ADVANCED_FEATURE_CONTRACT
    eckel_rule: str = ECKEL_RULE_VERSION
    explosive_rule: str = EXPLOSIVE_RULE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dt(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBAdvancedMetricError(f"{name} required")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBAdvancedMetricError(f"{name} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBAdvancedMetricError(f"{name} timezone required")
    return out


def _float(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in row and row[key] is not None:
            try:
                value = float(row[key])
            except (TypeError, ValueError):
                return None
            if isfinite(value):
                return value
            return None
    return None


def _bool(row: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key in row and row[key] is not None:
            value = row[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            text = str(value).strip().lower()
            if text in {"true", "t", "yes", "y", "1"}:
                return True
            if text in {"false", "f", "no", "n", "0"}:
                return False
    return None


def _text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _mean(values: list[float], name: str) -> float:
    if not values:
        raise CFBAdvancedMetricError(f"CFB_ADVANCED_SAMPLE_MISSING:{name}")
    return float(sum(values) / len(values))


def _rate(flags: list[bool], name: str) -> float:
    if not flags:
        raise CFBAdvancedMetricError(f"CFB_ADVANCED_SAMPLE_MISSING:{name}")
    return float(sum(flags) / len(flags))


def _is_rush(row: Mapping[str, Any]) -> bool:
    value = _text(row, "rush_pass", "rushPass").lower()
    if value:
        return value == "rush"
    rush = _bool(row, "rush")
    return rush is True


def _is_pass(row: Mapping[str, Any]) -> bool:
    value = _text(row, "rush_pass", "rushPass").lower()
    if value:
        return value in {"pass", "dropback"}
    passed = _bool(row, "pass")
    return passed is True


def _team_on_offense(row: Mapping[str, Any]) -> str:
    return _text(row, "pos_team", "offense", "possession_team")


def _team_on_defense(row: Mapping[str, Any]) -> str:
    explicit = _text(row, "def_pos_team", "defense")
    if explicit:
        return explicit
    home = _text(row, "home", "home_team")
    away = _text(row, "away", "away_team")
    offense = _team_on_offense(row)
    if home and away and offense:
        if offense == home:
            return away
        if offense == away:
            return home
    return ""


def _game_id(row: Mapping[str, Any]) -> str:
    return _text(row, "game_id", "gameId", "id_game")


def _drive_id(row: Mapping[str, Any]) -> str:
    value = _text(row, "drive_id", "driveId")
    if not value:
        raise CFBAdvancedMetricError("CFB_ADVANCED_DRIVE_ID_MISSING")
    return value


def _game_start(row: Mapping[str, Any]) -> datetime:
    for key in ("game_start_ts", "start_date", "startDate", "start_time"):
        if row.get(key) not in (None, ""):
            return _dt(row[key], key)
    raise CFBAdvancedMetricError("CFB_ADVANCED_GAME_START_MISSING")


def _epa(row: Mapping[str, Any]) -> float:
    value = _float(row, "EPA", "epa")
    if value is None:
        raise CFBAdvancedMetricError("CFB_ADVANCED_EPA_MISSING")
    return value


def _success(row: Mapping[str, Any]) -> bool:
    value = _bool(row, "success", "successful")
    if value is None:
        raise CFBAdvancedMetricError("CFB_ADVANCED_SUCCESS_MISSING")
    return value


def _yards_gained(row: Mapping[str, Any]) -> float:
    value = _float(row, "yards_gained", "yardsGained", "yards")
    if value is None:
        raise CFBAdvancedMetricError("CFB_ADVANCED_YARDS_MISSING")
    return value


def _down(row: Mapping[str, Any]) -> int:
    value = _float(row, "down")
    if value is None:
        raise CFBAdvancedMetricError("CFB_ADVANCED_DOWN_MISSING")
    return int(value)


def _distance(row: Mapping[str, Any]) -> float:
    value = _float(row, "distance", "ydstogo")
    if value is None:
        raise CFBAdvancedMetricError("CFB_ADVANCED_DISTANCE_MISSING")
    return value


def _yards_to_goal(row: Mapping[str, Any]) -> float | None:
    return _float(row, "yards_to_goal", "yardsToGoal", "yards_to_goal_before")


def _score_delta(row: Mapping[str, Any]) -> float:
    value = _float(row, "points_scored", "pointsGained", "score_delta")
    if value is not None:
        return max(0.0, value)
    scoring = _bool(row, "scoring")
    return 1.0 if scoring else 0.0


def _start_field_position(row: Mapping[str, Any]) -> float | None:
    ytg = _yards_to_goal(row)
    return None if ytg is None else 100.0 - ytg


def build_team_advanced_metrics(
    plays: Iterable[Mapping[str, Any]],
    *,
    team: str,
    feature_asof_ts: datetime | str,
    target_game_start_ts: datetime | str,
) -> CFBTeamAdvancedMetrics:
    team_name = str(team or "").strip()
    if not team_name:
        raise CFBAdvancedMetricError("CFB_ADVANCED_TEAM_REQUIRED")
    asof = _dt(feature_asof_ts, "feature_asof_ts")
    target_start = _dt(target_game_start_ts, "target_game_start_ts")
    if not asof < target_start:
        raise CFBAdvancedMetricError("FEATURE_ASOF_NOT_BEFORE_GAME_START")

    prior: list[Mapping[str, Any]] = []
    for raw in plays:
        if not isinstance(raw, Mapping):
            raise CFBAdvancedMetricError("CFB_ADVANCED_PLAY_NOT_MAPPING")
        if _game_start(raw) >= target_start:
            continue
        if _bool(raw, "garbage_time", "garbageTime") is True:
            continue
        prior.append(raw)
    if not prior:
        raise CFBAdvancedMetricError("CFB_ADVANCED_NO_PRIOR_PLAYS")

    offense = [row for row in prior if _team_on_offense(row) == team_name and (_is_rush(row) or _is_pass(row))]
    defense = [row for row in prior if _team_on_defense(row) == team_name and (_is_rush(row) or _is_pass(row))]
    if not offense or not defense:
        raise CFBAdvancedMetricError("CFB_ADVANCED_TWO_WAY_SAMPLE_REQUIRED")

    off_rush = [row for row in offense if _is_rush(row)]
    off_pass = [row for row in offense if _is_pass(row)]
    def_rush = [row for row in defense if _is_rush(row)]
    def_pass = [row for row in defense if _is_pass(row)]
    if not off_rush or not off_pass or not def_rush or not def_pass:
        raise CFBAdvancedMetricError("CFB_ADVANCED_RUSH_PASS_SAMPLE_REQUIRED")

    early = [row for row in offense if _down(row) in (1, 2)]
    late = [row for row in offense if _down(row) in (3, 4)]
    if not early or not late:
        raise CFBAdvancedMetricError("CFB_ADVANCED_DOWN_SAMPLE_REQUIRED")

    drives: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in offense:
        key = (_game_id(row), _drive_id(row))
        drives.setdefault(key, []).append(row)
    if not drives:
        raise CFBAdvancedMetricError("CFB_ADVANCED_DRIVES_MISSING")

    scoring_opps = 0
    eckel_points = 0.0
    total_points = 0.0
    starts: list[float] = []
    for rows in drives.values():
        start_fp = _start_field_position(rows[0])
        if start_fp is not None:
            starts.append(start_fp)
        reached_opp40 = any((ytg := _yards_to_goal(row)) is not None and ytg <= 40.0 for row in rows)
        drive_points = sum(_score_delta(row) for row in rows)
        total_points += drive_points
        if reached_opp40 or drive_points > 0:
            scoring_opps += 1
            eckel_points += drive_points

    games = {_game_id(row) for row in offense if _game_id(row)}
    explosive_flags = [
        (_is_rush(row) and _yards_gained(row) >= 10.0)
        or (_is_pass(row) and _yards_gained(row) >= 20.0)
        for row in offense
    ]
    late_conversions = [_yards_gained(row) >= _distance(row) for row in late]

    return CFBTeamAdvancedMetrics(
        team=team_name,
        sample_games=len(games),
        offensive_plays=len(offense),
        defensive_plays=len(defense),
        drives=len(drives),
        off_epa_rush=_mean([_epa(row) for row in off_rush], "off_epa_rush"),
        off_epa_dropback=_mean([_epa(row) for row in off_pass], "off_epa_dropback"),
        def_epa_rush_allowed=_mean([_epa(row) for row in def_rush], "def_epa_rush_allowed"),
        def_epa_dropback_allowed=_mean([_epa(row) for row in def_pass], "def_epa_dropback_allowed"),
        off_success_rate=_rate([_success(row) for row in offense], "off_success_rate"),
        off_rush_success_rate=_rate([_success(row) for row in off_rush], "off_rush_success_rate"),
        off_dropback_success_rate=_rate([_success(row) for row in off_pass], "off_dropback_success_rate"),
        def_success_rate_allowed=_rate([_success(row) for row in defense], "def_success_rate_allowed"),
        early_down_epa=_mean([_epa(row) for row in early], "early_down_epa"),
        late_down_conversion_rate=_rate(late_conversions, "late_down_conversion_rate"),
        eckel_rate=float(scoring_opps / len(drives)),
        points_per_eckel=float(eckel_points / scoring_opps) if scoring_opps else 0.0,
        points_per_drive=float(total_points / len(drives)),
        net_field_position=_mean(starts, "net_field_position"),
        explosive_rate=_rate(explosive_flags, "explosive_rate"),
        feature_asof_ts=asof.isoformat(),
    )
