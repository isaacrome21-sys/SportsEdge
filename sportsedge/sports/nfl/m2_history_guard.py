"""Fail-closed availability guard for production NFL M2 history rows.

The low-level historical feature producer historically represented unavailable
pregame state with numeric zeros. A zero can be a legitimate observed rate, so
production evaluation must never infer availability from the feature value
itself. This wrapper independently tracks the denominators behind the required
historical features and only releases rows whose pregame state is actually
observed.

Structural burn-in rows (for example Week 1 with no current-season sample) are
excluded from evaluation but still update state for later games. Missing prior
season or quarterback history is treated the same way: it cannot become a
neutral zero feature row.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from .m2_history_features import (
    _bool,
    _float,
    _game_sort_key,
    _int,
    _is_pass,
    _is_rush,
    build_nfl_m2_history_rows as _build_core_history_rows,
)


_REQUIRED_TEAM_DENOMINATORS = (
    "off_plays",
    "def_plays",
    "pass_plays",
    "rush_plays",
    "pressure_allowed_n",
    "pressure_for_n",
)


def _participation_pressure(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, int], bool]:
    out: dict[tuple[str, int], bool] = {}
    for raw in rows:
        gid = str(raw.get("nflverse_game_id") or raw.get("game_id") or "").strip()
        play_id = _int(raw.get("play_id"))
        value = _bool(raw.get("was_pressure"))
        if gid and play_id is not None and value is not None:
            out[(gid, play_id)] = value
    return out


def _game_denominators(
    pbp_rows: Iterable[Mapping[str, Any]],
    participation_rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], dict[str, int]], dict[tuple[str, str], int]]:
    pressure = _participation_pressure(participation_rows)
    team: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    qb: dict[tuple[str, str], int] = defaultdict(int)

    for raw in pbp_rows:
        gid = str(raw.get("game_id") or raw.get("nflverse_game_id") or "").strip()
        offense = str(raw.get("posteam") or raw.get("possession_team") or "").strip()
        defense = str(raw.get("defteam") or "").strip()
        if not gid or not offense or not defense or _float(raw.get("epa")) is None:
            continue

        team[(gid, offense)]["off_plays"] += 1
        team[(gid, defense)]["def_plays"] += 1
        if _is_pass(raw):
            team[(gid, offense)]["pass_plays"] += 1
        if _is_rush(raw):
            team[(gid, offense)]["rush_plays"] += 1

        play_id = _int(raw.get("play_id"))
        dropback = _bool(raw.get("qb_dropback")) is True
        if dropback and play_id is not None and (gid, play_id) in pressure:
            team[(gid, offense)]["pressure_allowed_n"] += 1
            team[(gid, defense)]["pressure_for_n"] += 1

        passer = str(raw.get("passer_player_id") or raw.get("passer_id") or "").strip()
        if dropback and passer:
            qb[(gid, passer)] += 1

    return dict(team), dict(qb)


def _team_history_available(state: Mapping[str, int]) -> bool:
    return all(int(state.get(name, 0)) > 0 for name in _REQUIRED_TEAM_DENOMINATORS)


def _add_counts(target: dict[str, int], source: Mapping[str, int]) -> None:
    for key, value in source.items():
        target[key] = int(target.get(key, 0)) + int(value)


def build_nfl_m2_history_rows(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
    participation_rows: Iterable[Mapping[str, Any]],
    depth_rows: Iterable[Mapping[str, Any]],
    stadium_rows: Iterable[Mapping[str, Any]],
    *,
    prior_decay_curves: Mapping[int, Mapping[int, float]],
) -> list[dict[str, Any]]:
    """Return only M2 rows backed by observed pregame historical state.

    The core builder still sees every game so excluded burn-in games update its
    strictly-prior state. Filtering happens afterward using an independent
    denominator ledger; therefore a returned numeric zero always means an
    observed zero rate, never "history unavailable".
    """
    schedule = [dict(row) for row in schedule_rows]
    pbp = [dict(row) for row in pbp_rows]
    participation = [dict(row) for row in participation_rows]
    depth = [dict(row) for row in depth_rows]
    stadiums = [dict(row) for row in stadium_rows]

    built = _build_core_history_rows(
        schedule,
        pbp,
        participation,
        depth,
        stadiums,
        prior_decay_curves=prior_decay_curves,
    )
    built_by_id = {str(row.get("game_id") or ""): row for row in built}
    game_team, game_qb = _game_denominators(pbp, participation)

    season_state: dict[tuple[int, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    qb_state: dict[str, int] = defaultdict(int)
    league_qb_dropbacks = 0
    safe: list[dict[str, Any]] = []

    games = [row for row in schedule if str(row.get("game_type") or "REG").upper() == "REG"]
    games.sort(key=_game_sort_key)
    for game in games:
        gid = str(game.get("game_id") or "").strip()
        season = _int(game.get("season"))
        home = str(game.get("home_team") or "").strip()
        away = str(game.get("away_team") or "").strip()
        row = built_by_id.get(gid)

        if row is not None and season is not None:
            home_state = season_state[(season, home)]
            away_state = season_state[(season, away)]
            previous_home = season_state[(season - 1, home)]
            previous_away = season_state[(season - 1, away)]
            home_qb = str((row.get("home_features") or {}).get("qb_id") or "").strip()
            away_qb = str((row.get("away_features") or {}).get("qb_id") or "").strip()

            current_available = _team_history_available(home_state) and _team_history_available(away_state)
            prior_available = int(previous_home.get("off_plays", 0)) > 0 and int(previous_away.get("off_plays", 0)) > 0
            qb_available = (
                bool(home_qb)
                and bool(away_qb)
                and int(qb_state.get(home_qb, 0)) > 0
                and int(qb_state.get(away_qb, 0)) > 0
                and league_qb_dropbacks > 0
            )

            if current_available and prior_available and qb_available:
                guarded = dict(row)
                guarded["history_availability_status"] = "AVAILABLE"
                guarded["history_zero_fill_guard"] = "PASS"
                safe.append(guarded)

        # Realized current-game information enters state only after eligibility
        # for this game has been decided.
        if season is not None:
            for team_name in (home, away):
                counts = game_team.get((gid, team_name))
                if counts:
                    _add_counts(season_state[(season, team_name)], counts)
        for (game_id, qb_id), dropbacks in game_qb.items():
            if game_id != gid:
                continue
            qb_state[qb_id] += int(dropbacks)
            league_qb_dropbacks += int(dropbacks)

    return safe
