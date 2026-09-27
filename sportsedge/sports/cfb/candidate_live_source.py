"""Point-in-time live feature assembly for selected CFB candidate families.

The frozen candidate transforms require both prior-season and current-season-through-
prior-week snapshots plus games-in-sample. This module supplies that exact row shape
without consulting sportsbook prices or future game outcomes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .source import (
    CFBSourceError,
    CFBTeamMetrics,
    _auth,
    _cfbd_url,
    _json_get,
    fetch_cfbd_team_metrics,
)

CFB_CANDIDATE_LIVE_SOURCE_CONTRACT = "CFB_CANDIDATE_DUAL_SNAPSHOT_LIVE_V1"


def games_in_sample_by_team(
    game_rows: Iterable[Mapping[str, Any]],
    *,
    through_week: int,
) -> dict[str, int]:
    """Count completed same-season games no later than the PIT week boundary."""
    out: dict[str, int] = {}
    for row in game_rows:
        if not isinstance(row, Mapping) or row.get("completed") is not True:
            continue
        try:
            week = int(row.get("week", 0))
        except (TypeError, ValueError):
            continue
        if week < 1 or week > int(through_week):
            continue
        for key in ("homeTeam", "awayTeam"):
            team = str(row.get(key) or "").strip()
            if team:
                out[team] = out.get(team, 0) + 1
    return out


def _metric_dict(metric: CFBTeamMetrics | Mapping[str, Any], *, games_in_sample: int) -> dict[str, Any]:
    if isinstance(metric, CFBTeamMetrics):
        row = metric.to_dict()
    elif isinstance(metric, Mapping):
        row = dict(metric)
    else:
        raise CFBSourceError("CFB_CANDIDATE_METRIC_MAPPING_REQUIRED")
    games = int(games_in_sample)
    if games < 0:
        raise CFBSourceError("CFB_CANDIDATE_GAMES_IN_SAMPLE_NEGATIVE")
    row["games_in_sample"] = games
    return row


def build_candidate_metric_snapshots(
    *,
    season: int,
    week: int,
    prior_metrics: Mapping[str, CFBTeamMetrics | Mapping[str, Any]],
    current_metrics: Mapping[str, CFBTeamMetrics | Mapping[str, Any]] | None,
    games_in_sample: Mapping[str, int] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return exact per-team prior/current snapshots required by candidate transforms."""
    season_i, week_i = int(season), int(week)
    if week_i < 1:
        raise CFBSourceError("CFB_CANDIDATE_WEEK_INVALID")
    out: dict[str, dict[str, dict[str, Any]]] = {}
    if not prior_metrics:
        raise CFBSourceError("CFB_CANDIDATE_PRIOR_METRICS_EMPTY")

    for team, prior in prior_metrics.items():
        prior_row = _metric_dict(prior, games_in_sample=0)
        if int(prior_row.get("season", -1)) != season_i - 1:
            raise CFBSourceError(f"CFB_CANDIDATE_PRIOR_SEASON_INVALID:{team}")
        if str(prior_row.get("sample_source") or "").upper() != "PRIOR_SEASON_FALLBACK":
            raise CFBSourceError(f"CFB_CANDIDATE_PRIOR_SOURCE_INVALID:{team}")

        if week_i == 1:
            current_row = dict(prior_row)
            current_row["games_in_sample"] = 0
        else:
            if current_metrics is None or team not in current_metrics:
                raise CFBSourceError(f"CFB_CANDIDATE_CURRENT_METRICS_MISSING:{team}")
            games = int((games_in_sample or {}).get(team, 0))
            current_row = _metric_dict(current_metrics[team], games_in_sample=games)
            if int(current_row.get("season", -1)) != season_i:
                raise CFBSourceError(f"CFB_CANDIDATE_CURRENT_SEASON_INVALID:{team}")
            if int(current_row.get("through_week", -1)) != week_i - 1:
                raise CFBSourceError(f"CFB_CANDIDATE_CURRENT_WEEK_INVALID:{team}")
            if str(current_row.get("sample_source") or "").upper() != "CURRENT_SEASON_PRIOR_WEEKS":
                raise CFBSourceError(f"CFB_CANDIDATE_CURRENT_SOURCE_INVALID:{team}")

        out[str(team)] = {"prior": prior_row, "current": current_row}
    return out


def fetch_cfbd_candidate_metric_snapshots(
    *,
    season: int,
    week: int,
    cfbd_api_key: str,
    now: datetime,
    opener: Callable = urlopen,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Fetch dual snapshots at the target game's PIT boundary.

    Week 1 makes only the prior-season metric calls and aliases current to prior with
    games_in_sample=0. Week 2+ additionally fetches current metrics through week-1 and
    completed same-season games solely to count games in sample.
    """
    season_i, week_i = int(season), int(week)
    prior = fetch_cfbd_team_metrics(
        season=season_i,
        week=1,
        cfbd_api_key=cfbd_api_key,
        now=now,
        opener=opener,
    )
    if week_i == 1:
        return build_candidate_metric_snapshots(
            season=season_i,
            week=week_i,
            prior_metrics=prior,
            current_metrics=None,
            games_in_sample=None,
        )

    current = fetch_cfbd_team_metrics(
        season=season_i,
        week=week_i,
        cfbd_api_key=cfbd_api_key,
        now=now,
        opener=opener,
    )
    raw_games = _json_get(
        _cfbd_url("/games", {"year": season_i, "seasonType": "regular", "classification": "fbs"}),
        headers=_auth(cfbd_api_key),
        opener=opener,
    )
    if not isinstance(raw_games, list):
        raise CFBSourceError("CFB_CANDIDATE_GAMES_NOT_LIST")
    counts = games_in_sample_by_team(raw_games, through_week=week_i - 1)
    return build_candidate_metric_snapshots(
        season=season_i,
        week=week_i,
        prior_metrics=prior,
        current_metrics=current,
        games_in_sample=counts,
    )


def attach_candidate_snapshots_to_game_row(
    row: Mapping[str, Any],
    *,
    home_team: str,
    away_team: str,
    snapshots: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Attach exact dual snapshots while preserving the caller's market-blind row."""
    home, away = str(home_team), str(away_team)
    if home not in snapshots or away not in snapshots:
        raise CFBSourceError("CFB_CANDIDATE_GAME_TEAM_SNAPSHOT_MISSING")
    out = dict(row)
    out["home_prior_metrics"] = dict(snapshots[home]["prior"])
    out["away_prior_metrics"] = dict(snapshots[away]["prior"])
    out["home_current_metrics"] = dict(snapshots[home]["current"])
    out["away_current_metrics"] = dict(snapshots[away]["current"])
    # Keep legacy fields present for callers that inspect them; the candidate transform
    # overwrites these deterministically before the numeric feature vector is built.
    out["home_metrics"] = dict(snapshots[home]["current"])
    out["away_metrics"] = dict(snapshots[away]["current"])
    return out


__all__ = [
    "CFB_CANDIDATE_LIVE_SOURCE_CONTRACT",
    "attach_candidate_snapshots_to_game_row",
    "build_candidate_metric_snapshots",
    "fetch_cfbd_candidate_metric_snapshots",
    "games_in_sample_by_team",
]
