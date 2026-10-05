"""Build the NFL score-conditioned TD composition prior from frozen score-count sources."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable, Mapping, Sequence

from sportsedge.sports.nfl.score_counts_features import (
    TeamGame,
    _prepare_schedule,
    aggregate_game_pbp,
)


class ScoreCountScoringPriorError(ValueError):
    pass


def _score_value(value: Any, field: str) -> int:
    if isinstance(value, bool) or value in (None, ""):
        raise ScoreCountScoringPriorError(f"{field}:FINAL_SCORE_REQUIRED")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountScoringPriorError(f"{field}:FINAL_SCORE_REQUIRED") from exc
    if number < 0 or number != int(number):
        raise ScoreCountScoringPriorError(f"{field}:NONNEGATIVE_INTEGER_REQUIRED")
    return int(number)


def _schedule_score(raw: Mapping[str, Any], side: str) -> int:
    if side == "home":
        keys = ("home_score", "home_points", "homePoints")
    elif side == "away":
        keys = ("away_score", "away_points", "awayPoints")
    else:
        raise ScoreCountScoringPriorError("TEAM_SIDE_INVALID")
    for key in keys:
        if raw.get(key) not in (None, ""):
            return _score_value(raw.get(key), key)
    raise ScoreCountScoringPriorError(f"{side.upper()}_FINAL_SCORE_REQUIRED")


def _composition(label: TeamGame) -> dict[str, int]:
    touchdowns = int(label.total_touchdowns)
    pat = int(label.pat_made)
    two = int(label.two_point_made)
    fg = int(label.made_field_goals)
    safeties = int(label.safeties)
    if pat + two > touchdowns:
        raise ScoreCountScoringPriorError("POST_TD_TRIES_EXCEED_TOUCHDOWNS")
    score = 6 * touchdowns + pat + 2 * two + 3 * fg + 2 * safeties
    return {
        "touchdowns": touchdowns,
        "extra_points_made": pat,
        "two_point_made": two,
        "field_goals_made": fg,
        "safeties": safeties,
        "score": score,
    }


def build_scoring_composition_rows(
    *,
    schedule_rows: Sequence[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
    seasons: Sequence[int],
    conservative_completion_lag_hours: int,
    excluded_game_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Return one completed team-game scoring row per frozen PBP team.

    Completion availability is conservatively assigned to kickoff + a fixed
    positive lag. The downstream PIT fitter still requires this timestamp to
    precede the requested as-of cutoff.
    """
    lag = int(conservative_completion_lag_hours)
    if lag < 1:
        raise ScoreCountScoringPriorError("COMPLETION_LAG_POSITIVE_REQUIRED")
    excluded = {str(v).strip() for v in excluded_game_ids if str(v).strip()}

    schedule = {
        gid: (start, season, week, home, away, raw)
        for start, gid, season, week, home, away, raw
        in _prepare_schedule(schedule_rows, seasons)
    }
    team_game, _qbs = aggregate_game_pbp(pbp_rows)
    pbp_game_ids = sorted({gid for gid, _team in team_game})

    rows: list[dict[str, Any]] = []
    for gid in pbp_game_ids:
        if gid in excluded:
            continue
        entry = schedule.get(gid)
        if entry is None:
            raise ScoreCountScoringPriorError(f"PBP_GAME_NOT_IN_FROZEN_SCHEDULE:{gid}")
        start, season, week, home, away, raw = entry
        completed_at = (start + timedelta(hours=lag)).isoformat()
        for side, team in (("home", home), ("away", away)):
            label = team_game.get((gid, team))
            if label is None:
                raise ScoreCountScoringPriorError(f"PBP_TEAM_LABEL_MISSING:{gid}:{team}")
            composition = _composition(label)
            scheduled = _schedule_score(raw, side)
            if composition["score"] != scheduled:
                raise ScoreCountScoringPriorError(
                    f"SCORING_COMPOSITION_SCHEDULE_MISMATCH:{gid}:{team}:"
                    f"{composition['score']}:{scheduled}"
                )
            rows.append({
                "game_id": gid,
                "team": team,
                "season": int(season),
                "week": int(week),
                "completed_at": completed_at,
                **composition,
                "source": "NFLVERSE_FROZEN_SCORE_COUNTS_PBP",
            })

    if not rows:
        raise ScoreCountScoringPriorError("SCORING_COMPOSITION_ROWS_EMPTY")
    rows.sort(key=lambda row: (row["completed_at"], row["game_id"], row["team"]))
    return rows


__all__ = [
    "ScoreCountScoringPriorError",
    "build_scoring_composition_rows",
]
