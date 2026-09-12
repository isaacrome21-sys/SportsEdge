"""Point-in-time drive-rate state for the NFL V2E diagnostic.

The feature is deliberately minimal and preregistered: before each retained game
date, a team's prior offensive drives per retained game are compared with the
league's prior team-drives per retained game. Games on the same calendar date
share the same pre-date information set, so no result from a current-date game
can leak into another current-date prediction.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from math import isfinite
from typing import Any, Iterable, Mapping

from .m2_v2e_drives import (
    V2E_TEAM_ALIAS_POLICY,
    _SCHEDULE_TO_PBP_TEAM_ALIAS,
)

V2E_DRIVE_RATE_FIELD = "pit_drive_rate_delta"
V2E_DRIVE_RATE_CONTRACT = "NFL_V2E_PRIOR_GAME_DRIVE_RATE_DELTA_V1"
V2E_DRIVE_RATE_SCOPE = "PRIOR_RETAINED_GAME_DATES_ONLY"


def _canonical_franchise(team: Any) -> str:
    value = str(team or "").strip()
    if not value:
        raise ValueError("NFL_V2E_DRIVE_RATE_TEAM_IDENTITY_MISSING")
    return _SCHEDULE_TO_PBP_TEAM_ALIAS.get(value, value)


def _game_date(row: Mapping[str, Any]) -> str:
    raw = str(row.get("gameday") or "").strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("NFL_V2E_DRIVE_RATE_GAMEDAY_INVALID") from exc
    return parsed.isoformat()


def _positive_int(value: Any, *, reason: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    integer = int(number)
    if not isfinite(number) or number != integer or integer <= 0:
        raise ValueError(reason)
    return integer


def build_v2e_pit_drive_rate_by_game(
    schedule_rows: Iterable[Mapping[str, Any]],
    drive_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    """Build a deterministic prior-game drive-rate delta for each retained game.

    For every game date, features are emitted from counters frozen at the end of
    the previous retained game date. Only after all games on the date receive
    their feature are that date's realized drive counts added to the counters.

    If neither the team nor league has prior retained-game evidence, the delta
    is exactly 0.0. A team with no prior evidence inherits the prior league mean,
    also producing a 0.0 delta rather than an arbitrary hard-coded baseline.
    """
    schedule: dict[str, dict[str, Any]] = {}
    for raw in schedule_rows:
        row = dict(raw)
        game_id = str(row.get("game_id") or "").strip()
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        gameday = _game_date(row)
        if not game_id or not home or not away or home == away:
            raise ValueError("NFL_V2E_DRIVE_RATE_SCHEDULE_IDENTITY_INVALID")
        if game_id in schedule:
            raise ValueError(f"NFL_V2E_DRIVE_RATE_DUPLICATE_GAME:{game_id}")
        schedule[game_id] = {
            "game_id": game_id,
            "gameday": gameday,
            "home_team": home,
            "away_team": away,
        }

    drives: dict[str, dict[str, Any]] = {}
    for raw in drive_rows:
        row = dict(raw)
        game_id = str(row.get("game_id") or "").strip()
        if not game_id or game_id in drives:
            raise ValueError("NFL_V2E_DRIVE_RATE_DRIVE_IDENTITY_INVALID")
        drives[game_id] = row

    if set(schedule) != set(drives):
        raise ValueError("NFL_V2E_DRIVE_RATE_COHORT_MISMATCH")
    if not schedule:
        return {}

    games_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for game_id, scheduled in schedule.items():
        target = drives[game_id]
        if (
            str(target.get("home_team") or "").strip() != scheduled["home_team"]
            or str(target.get("away_team") or "").strip() != scheduled["away_team"]
        ):
            raise ValueError(f"NFL_V2E_DRIVE_RATE_TEAM_IDENTITY_MISMATCH:{game_id}")
        if str(target.get("team_alias_policy") or "") != V2E_TEAM_ALIAS_POLICY:
            raise ValueError(f"NFL_V2E_DRIVE_RATE_ALIAS_POLICY_MISMATCH:{game_id}")
        games_by_date[scheduled["gameday"]].append(scheduled)

    team_drives: dict[str, int] = defaultdict(int)
    team_games: dict[str, int] = defaultdict(int)
    league_drives = 0
    league_team_games = 0
    output: dict[str, dict[str, float]] = {}

    for gameday in sorted(games_by_date):
        date_games = sorted(games_by_date[gameday], key=lambda row: row["game_id"])

        seen_teams: set[str] = set()
        for scheduled in date_games:
            for team in (scheduled["home_team"], scheduled["away_team"]):
                canonical = _canonical_franchise(team)
                if canonical in seen_teams:
                    raise ValueError(
                        f"NFL_V2E_DRIVE_RATE_TEAM_DOUBLEHEADER_UNSUPPORTED:{gameday}:{canonical}"
                    )
                seen_teams.add(canonical)

        league_rate = (
            float(league_drives) / float(league_team_games)
            if league_team_games > 0
            else None
        )
        for scheduled in date_games:
            game_id = scheduled["game_id"]
            values: dict[str, float] = {}
            for side in ("home", "away"):
                team = _canonical_franchise(scheduled[f"{side}_team"])
                if league_rate is None:
                    delta = 0.0
                else:
                    team_rate = (
                        float(team_drives[team]) / float(team_games[team])
                        if team_games[team] > 0
                        else league_rate
                    )
                    delta = team_rate - league_rate
                values[side] = float(delta)
            output[game_id] = values

        # Update only after every game on the date has received its feature.
        for scheduled in date_games:
            game_id = scheduled["game_id"]
            target = drives[game_id]
            for side in ("home", "away"):
                count = _positive_int(
                    target.get(f"{side}_drives"),
                    reason=f"NFL_V2E_DRIVE_RATE_COUNT_INVALID:{game_id}:{side}",
                )
                team = _canonical_franchise(scheduled[f"{side}_team"])
                team_drives[team] += count
                team_games[team] += 1
                league_drives += count
                league_team_games += 1

    return output
