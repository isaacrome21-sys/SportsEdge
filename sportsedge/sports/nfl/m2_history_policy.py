"""Neutral-site and historical-stadium policy wrapper for NFL production M2.

Neutral-site games are valuable prior-state observations but cannot be priced
with home-team stadium geography when the exact venue is unresolved. The
production evidence policy therefore supports explicit neutral-site handling.

The wrapper also repairs one narrow source-interval artifact for travel features:
a team can play away after its final home game at a stadium, so a stadium table
whose ``last_game_date`` is the last *home* game can stop before the franchise's
season actually ends. In that bounded away-only case, the last known home origin
is carried forward for at most 28 days. The game venue is never inferred, home
games are never bridged, and distant or ambiguous gaps remain fail-closed.

Depth-chart input is projected to rows that the exact production starter selector
could ever accept. This is a semantics-preserving performance boundary.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any
import warnings

from .m2_history_features import _float
from .m2_history_features import build_nfl_m2_history_rows as _build_core_history_rows

_ALLOWED_POLICIES = {"error", "exclude_from_evaluation"}
_KNOWN_ROOF = {"outdoors", "open", "dome", "closed"}
_SEALED_ROOF = {"dome", "closed"}
_MAX_POSTCLOSING_AWAY_ORIGIN_GAP_DAYS = 28


def _rank_one(value: Any) -> bool:
    try:
        return int(float(value)) == 1
    except (TypeError, ValueError):
        return False


def _date_value(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _stadium_team(row: Mapping[str, Any]) -> str:
    return str(row.get("team_fastr") or row.get("team") or "").strip()


def _stadium_geo_complete(row: Mapping[str, Any]) -> bool:
    try:
        float(row.get("lat") or "")
        float(row.get("lon") or "")
        float(row.get("tz_offset") or "")
    except (TypeError, ValueError):
        return False
    return True


def _stadium_active(row: Mapping[str, Any], *, team: str, gameday: date) -> bool:
    if _stadium_team(row) != team or not _stadium_geo_complete(row):
        return False
    first = _date_value(row.get("first_game_date")) or date.min
    last = _date_value(row.get("last_game_date")) or date.max
    return first <= gameday <= last


def bridge_postclosing_away_origins(
    schedule_rows: Iterable[Mapping[str, Any]],
    stadium_rows: Iterable[Mapping[str, Any]],
    *,
    max_gap_days: int = _MAX_POSTCLOSING_AWAY_ORIGIN_GAP_DAYS,
) -> list[dict[str, Any]]:
    """Carry the last known home origin through a short away-only season tail.

    The source interval is extended only when an away team has no active stadium
    on that date and there is one unique most-recent same-team stadium whose
    source ``last_game_date`` is within ``max_gap_days``. The distance is always
    measured from the original source boundary, so repeated away games cannot
    chain an unbounded extension. A future relocated stadium is never used.
    """
    if max_gap_days < 0:
        raise ValueError("NFL_POSTCLOSING_STADIUM_BRIDGE_GAP_INVALID")

    source = [dict(row) for row in stadium_rows]
    resolved = [dict(row) for row in source]
    games = [dict(row) for row in schedule_rows if str(row.get("game_type") or "REG").upper() == "REG"]
    games.sort(key=lambda row: (str(row.get("gameday") or row.get("game_date") or ""), str(row.get("game_id") or "")))

    for game in games:
        gameday = _date_value(game.get("gameday") or game.get("game_date"))
        team = str(game.get("away_team") or "").strip()
        if gameday is None or not team:
            continue
        if any(_stadium_active(row, team=team, gameday=gameday) for row in resolved):
            continue

        past: list[tuple[date, int]] = []
        for index, row in enumerate(source):
            if _stadium_team(row) != team or not _stadium_geo_complete(row):
                continue
            last = _date_value(row.get("last_game_date"))
            if last is None:
                continue
            gap = (gameday - last).days
            if 0 < gap <= max_gap_days:
                past.append((last, index))
        if not past:
            continue

        latest = max(last for last, _ in past)
        selected = [index for last, index in past if last == latest]
        if len(selected) != 1:
            raise ValueError(
                f"NFL_POSTCLOSING_STADIUM_BRIDGE_AMBIGUOUS:{team}:{gameday.isoformat()}:{latest.isoformat()}"
            )
        index = selected[0]
        resolved[index]["last_game_date"] = max(
            gameday,
            _date_value(resolved[index].get("last_game_date")) or gameday,
        ).isoformat()
        resolved[index]["sportsedge_origin_bridge"] = "POST_CLOSING_AWAY_TEAM_HOME_ORIGIN_PROXY"
        resolved[index]["sportsedge_source_last_game_date"] = latest.isoformat()

    return resolved


def _project_starter_depth_rows(
    depth_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep exactly the union of rows the production starter selector can use."""
    projected: list[dict[str, Any]] = []
    for raw in depth_rows:
        row = dict(raw)
        timestamped_position = str(
            row.get("pos_abb") or row.get("position") or row.get("depth_position") or ""
        ).upper()
        timestamped_candidate = (
            row.get("dt") not in (None, "")
            and timestamped_position == "QB"
            and _rank_one(row.get("pos_rank"))
        )

        weekly_position = str(row.get("depth_position") or row.get("position") or "").upper()
        weekly_rank = row.get("depth_team", row.get("pos_rank"))
        weekly_candidate = weekly_position == "QB" and _rank_one(weekly_rank)

        if timestamped_candidate or weekly_candidate:
            projected.append(row)
    return projected


def environment_exclusion_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons = []
    for field in ("home_rest", "away_rest"):
        value = _float(row.get(field))
        if isinstance(row.get(field), bool) or value is None or value < 0:
            reasons.append(f"NFL_{field.upper()}_INVALID")

    roof = str(row.get("roof") or "").strip().lower()
    if roof not in _KNOWN_ROOF:
        reasons.append("NFL_ROOF_INVALID")

    field = "wind_mph" if row.get("wind_mph") not in (None, "") else "wind"
    raw_wind = row.get(field)
    if roof in _SEALED_ROOF and raw_wind in (None, ""):
        wind = 0.0
    else:
        wind = _float(raw_wind)
    if isinstance(raw_wind, bool) or wind is None or wind < 0:
        reasons.append("NFL_WIND_INVALID")
    return reasons


def _normalize_policy_environment(row: dict[str, Any]) -> None:
    """Apply policy-owned structural environment values before strict core use.

    The core history builder intentionally never manufactures missing weather.
    This wrapper owns the narrower venue policy: for exact dome/closed rows only,
    an absent/blank provider wind value means no game-level wind exposure and is
    materialized as 0.0. Supplied malformed values are never overwritten.
    """
    roof = str(row.get("roof") or "").strip().lower()
    field = "wind_mph" if row.get("wind_mph") not in (None, "") else "wind"
    if roof in _SEALED_ROOF and row.get(field) in (None, ""):
        row["wind"] = 0.0


def build_nfl_m2_history_rows(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
    participation_rows: Iterable[Mapping[str, Any]],
    depth_rows: Iterable[Mapping[str, Any]],
    stadium_rows: Iterable[Mapping[str, Any]],
    *,
    prior_decay_curves: Mapping[int, Mapping[int, float]],
    neutral_site_policy: str = "error",
    exclusion_report: dict[int, dict[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """Build production-M2 rows under explicit neutral-site/stadium policies."""
    policy = str(neutral_site_policy).strip().lower()
    if policy not in _ALLOWED_POLICIES:
        raise ValueError(f"NFL_NEUTRAL_SITE_POLICY_INVALID:{neutral_site_policy}")

    schedule = [dict(row) for row in schedule_rows]
    weather_excluded_ids: set[str] = set()
    for row in schedule:
        if str(row.get("game_type") or "REG").upper() != "REG":
            continue
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            raise ValueError("NFL_HISTORY_GAME_IDENTITY_MISSING")
        season = int(row.get("season"))
        reasons = environment_exclusion_reasons(row)
        if reasons:
            weather_excluded_ids.add(game_id)
            if exclusion_report is None:
                warnings.warn(f"NFL_HISTORY_ROW_EXCLUDED:{season}:{game_id}:{','.join(reasons)}", RuntimeWarning)
            else:
                by_reason = exclusion_report.setdefault(season, {})
                reason = "|".join(sorted(reasons))
                by_reason[reason] = by_reason.get(reason, 0) + 1
        else:
            _normalize_policy_environment(row)
    depth = _project_starter_depth_rows(depth_rows)
    stadiums = bridge_postclosing_away_origins(schedule, stadium_rows)
    if policy == "error":
        return _build_core_history_rows(
            schedule,
            pbp_rows,
            participation_rows,
            depth,
            stadiums,
            prior_decay_curves=prior_decay_curves,
            evaluation_excluded_ids=weather_excluded_ids,
        )

    excluded_ids: set[str] = set()
    state_schedule: list[dict[str, Any]] = []
    for raw in schedule:
        row = dict(raw)
        location = str(row.get("location") or "Home").strip().lower()
        if location != "home":
            game_id = str(row.get("game_id") or "").strip()
            if not game_id:
                raise ValueError("NFL_HISTORY_GAME_IDENTITY_MISSING")
            excluded_ids.add(game_id)
            row["location"] = "Home"
        state_schedule.append(row)

    built = _build_core_history_rows(
        state_schedule,
        pbp_rows,
        participation_rows,
        depth,
        stadiums,
        prior_decay_curves=prior_decay_curves,
        evaluation_excluded_ids=weather_excluded_ids | excluded_ids,
    )
    return [row for row in built if str(row.get("game_id") or "") not in excluded_ids]
