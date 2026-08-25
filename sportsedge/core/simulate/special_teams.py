"""Structural Engine C special-teams readouts over Engine A paths.

The current Engine A drive/play candidate stores touchdowns as seven-point
bundled events. Until PAT/two-point plays are split into first-class events,
``xp_made`` is therefore the number of offensive seven-point TD events and
``kicking_points`` adds one bundled made XP per such touchdown. This convention
is explicit and must be replaced/validated before kicker-market promotion.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .drive_play import FootballPlayPath


@dataclass(frozen=True)
class TeamSpecialTeamsProfile:
    team: str
    kicker_id: str
    active: bool | None

    def __post_init__(self) -> None:
        if not str(self.team).strip():
            raise ValueError("SPECIAL_TEAMS_TEAM_REQUIRED")
        if not str(self.kicker_id).strip():
            raise ValueError("KICKER_ID_REQUIRED")
        if self.active is not None and not isinstance(self.active, bool):
            raise ValueError("KICKER_ACTIVE_STATE_INVALID")


def _price(samples: list[float], line: float) -> dict[str, float]:
    if not samples:
        raise ValueError("SPECIAL_TEAMS_SAMPLES_REQUIRED")
    n = float(len(samples))
    return {
        "over": sum(value > line for value in samples) / n,
        "under": sum(value < line for value in samples) / n,
        "push": sum(value == line for value in samples) / n,
    }


def derive_special_teams_market_readouts(
    paths: Iterable[FootballPlayPath],
    *,
    home: TeamSpecialTeamsProfile,
    away: TeamSpecialTeamsProfile,
    lines: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    rows = list(paths)
    if not rows:
        raise ValueError("ENGINE_A_PATHS_REQUIRED")
    if any(not isinstance(path, FootballPlayPath) for path in rows):
        raise TypeError("FOOTBALL_PLAY_PATH_REQUIRED")
    identity = (rows[0].game_id, rows[0].home_team, rows[0].away_team)
    if any((path.game_id, path.home_team, path.away_team) != identity for path in rows[1:]):
        raise ValueError("SPECIAL_TEAMS_ENSEMBLE_IDENTITY_MISMATCH")
    if home.team != rows[0].home_team or away.team != rows[0].away_team:
        raise ValueError("SPECIAL_TEAMS_PATH_TEAM_MISMATCH")
    if home.kicker_id == away.kicker_id:
        raise ValueError("KICKER_ID_COLLISION")

    for profile in (home, away):
        if profile.active is None:
            raise ValueError(f"SPECIAL_TEAMS_PARTICIPATION_UNRESOLVED:{profile.kicker_id}")
        if profile.active is not True:
            raise ValueError(f"STARTING_KICKER_INACTIVE:{profile.kicker_id}")

    market_lines = {
        str(market): {str(entity): float(line) for entity, line in entity_lines.items()}
        for market, entity_lines in (lines or {}).items()
    }
    allowed = {"fg_made", "kicking_points", "xp_made", "longest_fg_made"}
    unsupported = sorted(set(market_lines) - allowed)
    if unsupported:
        raise ValueError(f"SPECIAL_TEAMS_LINE_UNSUPPORTED:{unsupported[0]}")

    samples: dict[str, dict[str, list[float]]] = {
        "fg_made": {home.kicker_id: [], away.kicker_id: []},
        "kicking_points": {home.kicker_id: [], away.kicker_id: []},
        "xp_made": {home.kicker_id: [], away.kicker_id: []},
        "longest_fg_made": {home.team: [], away.team: []},
    }

    for path in rows:
        path.assert_reconciliation()
        for profile in (home, away):
            team = profile.team
            kicker = profile.kicker_id
            field_goals = [
                play for play in path.plays
                if play.possession == team and play.play_type.upper() == "FIELD_GOAL"
            ]
            made_field_goals = [play for play in field_goals if play.points == 3]
            if any(play.points not in {0, 3} for play in field_goals):
                raise ValueError("FIELD_GOAL_POINTS_INVALID_FOR_ENGINE_C")
            if any(play.points == 3 and play.kick_distance is None for play in field_goals):
                raise ValueError("MADE_FIELD_GOAL_DISTANCE_MISSING")
            offensive_tds = sum(
                play.possession == team
                and play.points == 7
                and play.play_type.upper() in {"PASS", "RUSH"}
                for play in path.plays
            )
            made = len(made_field_goals)
            longest = max((int(play.kick_distance) for play in made_field_goals), default=0)
            samples["fg_made"][kicker].append(float(made))
            samples["xp_made"][kicker].append(float(offensive_tds))
            samples["kicking_points"][kicker].append(float(3 * made + offensive_tds))
            samples["longest_fg_made"][team].append(float(longest))

    n = float(len(rows))
    out: dict[str, dict[str, dict[str, object]]] = {market: {} for market in samples}
    for market, entities in samples.items():
        for entity, values in entities.items():
            row: dict[str, object] = {
                "samples": tuple(values),
                "mean": sum(values) / n,
            }
            if entity in market_lines.get(market, {}):
                row["price"] = _price(values, market_lines[market][entity])
            out[market][entity] = row
    return out
