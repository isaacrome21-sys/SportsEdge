from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import ceil
from typing import Any, Callable, Iterable

from sportsedge.sports.nfl.auto_slate import discover_nfl_auto_games
from sportsedge.sports.nfl.context_autopull import NFLContextError

from .football_joint import build_nfl_joint_path_snapshot
from .sources.nfl_player_stats import build_prior_player_stat_history, fetch_nflverse_player_stats
from .types import DKPlayer

_TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(raw, raw)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("NFL_DFS_AUTO_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def _pool_pairs(players: Iterable[DKPlayer]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for player in players:
        if player.is_disabled:
            continue
        team, opponent = _team(player.team), _team(player.opponent)
        if team and opponent and team != opponent:
            pairs.add(tuple(sorted((team, opponent))))
    return pairs


def build_nfl_auto_projection_snapshot(
    *,
    players: Iterable[DKPlayer],
    slate_start: datetime,
    as_of: datetime | None = None,
    paths: int = 5000,
    seed: int | None = None,
    max_history_games: int = 10,
    schedule_discoverer: Callable[..., dict[str, Any]] = discover_nfl_auto_games,
    stats_fetcher: Callable[..., tuple[list[dict[str, str]], str, str]] = fetch_nflverse_player_stats,
) -> dict[str, Any]:
    """Resolve the DK player pool to one NFL week and build a joint DFS snapshot.

    This function performs no market/odds lookup. Schedule identity comes from the
    existing SportsEdge nflverse auto-slate source. Player production comes from
    nflverse weekly player stats, filtered strictly to weeks before the target game.
    """
    pool = [p for p in players if not p.is_disabled]
    if not pool:
        raise ValueError("NFL_DFS_AUTO_PLAYER_POOL_EMPTY")
    lock = _utc(slate_start)
    pit = _utc(as_of or datetime.now(timezone.utc))
    if pit >= lock:
        raise ValueError("NFL_DFS_AUTO_NOT_PREGAME")
    pairs = _pool_pairs(pool)
    if not pairs:
        raise ValueError("NFL_DFS_AUTO_MATCHUPS_MISSING")

    lead_minutes = max(0, int((lock - pit).total_seconds() // 60))
    horizon = max(24 * 60, lead_minutes + 36 * 60)
    plan = schedule_discoverer(
        as_of=pit,
        min_lead_minutes=0,
        horizon_minutes=horizon,
        game_types=("REG",),
    )
    discovered = []
    matched_pairs: set[tuple[str, str]] = set()
    for game in plan.get("games") or []:
        if not isinstance(game, dict):
            continue
        home = _team(game.get("home_team_id"))
        away = _team(game.get("away_team_id"))
        pair = tuple(sorted((home, away))) if home and away else ()
        if pair in pairs:
            discovered.append(game)
            matched_pairs.add(pair)
    missing_pairs = sorted(pairs - matched_pairs)
    if missing_pairs:
        raise NFLContextError("NFL_DFS_AUTO_SCHEDULE_MATCH_MISSING:" + json.dumps(missing_pairs))
    seasons = {int(game["season"]) for game in discovered if game.get("season") is not None}
    weeks = {int(game["week"]) for game in discovered if game.get("week") is not None}
    if len(seasons) != 1 or len(weeks) != 1:
        raise NFLContextError(f"NFL_DFS_AUTO_WEEK_AMBIGUOUS:{sorted(seasons)}:{sorted(weeks)}")
    season = next(iter(seasons))
    week = next(iter(weeks))

    current_rows: list[dict[str, str]] = []
    current_uri: str | None = None
    current_sha: str | None = None
    if week > 1:
        current_rows, current_uri, current_sha = stats_fetcher(season=season)
    else:
        try:
            current_rows, current_uri, current_sha = stats_fetcher(season=season)
        except Exception:
            current_rows, current_uri, current_sha = [], None, None
    prior_rows, prior_uri, prior_sha = stats_fetcher(season=season - 1)

    history = build_prior_player_stat_history(
        current_rows=current_rows,
        prior_rows=prior_rows,
        season=season,
        target_week=week,
        team_ids={_team(p.team) for p in pool},
        current_source_uri=current_uri,
        current_source_sha256=current_sha,
        prior_source_uri=prior_uri,
        prior_source_sha256=prior_sha,
        max_games=max_history_games,
    )
    if history["player_count"] < 2:
        raise ValueError("NFL_DFS_AUTO_HISTORY_TOO_SPARSE")

    if seed is None:
        seed_payload = {
            "sport": "NFL",
            "slate_start": lock.isoformat(),
            "season": season,
            "week": week,
            "schedule_sha": plan.get("schedule_source_sha256"),
            "current_sha": current_sha,
            "prior_sha": prior_sha,
            "player_ids": sorted(p.player_id for p in pool),
        }
        seed = int(sha256(json.dumps(seed_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:8], 16)

    snapshot = build_nfl_joint_path_snapshot(
        players=pool,
        history_payload=history,
        as_of=pit,
        paths=int(paths),
        seed=int(seed),
    )
    diagnostics = dict(snapshot.get("diagnostics") or {})
    diagnostics.update({
        "auto_projection": True,
        "schedule_source": "SPORTSEDGE_NFLVERSE_AUTO_SLATE",
        "schedule_source_sha256": plan.get("schedule_source_sha256"),
        "resolved_season": season,
        "resolved_week": week,
        "resolved_game_count": len(discovered),
        "resolved_matchup_count": len(matched_pairs),
        "history_player_count": history["player_count"],
        "history_current_source_status": history["current_source_status"],
        "history_max_games": history["max_games"],
        "projection_authority": "RESEARCH_ONLY_UNVALIDATED",
    })
    snapshot["diagnostics"] = diagnostics
    snapshot["auto_projection_context"] = {
        "as_of_utc": pit.isoformat(),
        "slate_start_utc": lock.isoformat(),
        "season": season,
        "week": week,
        "game_ids": sorted(str(game.get("game_id") or "") for game in discovered),
        "schedule_source_sha256": plan.get("schedule_source_sha256"),
    }
    return snapshot
