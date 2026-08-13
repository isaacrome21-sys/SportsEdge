"""Deterministic early projected MLB batting orders from official prior lineups only.

This module is a source/identity bridge, not a predictive betting model. It never
uses outcomes from the current slate, sportsbook data, or third-party lineup
predictions. When today's confirmed MLB batting order is unavailable, it projects
a 1-9 order from the team's most recent confirmed MLB starting lineups, requires
every selected player to remain on the active roster, and records the exact
historical game IDs used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .mlb_source import BASE, MLBSourceError, _get_json, fetch_boxscore, fetch_schedule, parse_confirmed_lineup, parse_game_start

SOURCE = "MLB_STATSAPI_PRIOR_CONFIRMED_LINEUPS"
LOOKBACK_DAYS = 21
MAX_LINEUPS = 6
MIN_LINEUPS = 3


@dataclass(frozen=True)
class ProjectedLineup:
    team_id: int
    player_ids: tuple[int, ...]
    batting_slots: tuple[int, ...]
    source_game_pks: tuple[int, ...]
    latest_source_date: str
    retrieved_at_utc: str
    source: str = SOURCE

    def top3(self) -> tuple[int, int, int]:
        if self.batting_slots != tuple(range(1, 10)) or len(self.player_ids) != 9:
            raise MLBSourceError("MLB_PROJECTED_LINEUP_NOT_COMPLETE")
        return tuple(self.player_ids[:3])  # type: ignore[return-value]


def _starting_nine(rows: Iterable[Mapping[str, Any]]) -> tuple[int, ...]:
    by_slot: dict[int, int] = {}
    for raw in rows:
        try:
            slot = int(raw.get("slot")); seq = int(raw.get("sequence", 0)); pid = int(raw.get("player_id"))
        except (TypeError, ValueError):
            continue
        if not 1 <= slot <= 9 or seq != 0 or pid <= 0:
            continue
        if slot in by_slot and by_slot[slot] != pid:
            raise MLBSourceError("MLB_PRIOR_LINEUP_SLOT_AMBIGUOUS")
        by_slot[slot] = pid
    if set(by_slot) != set(range(1, 10)) or len(set(by_slot.values())) != 9:
        raise MLBSourceError("MLB_PRIOR_LINEUP_INCOMPLETE")
    return tuple(by_slot[s] for s in range(1, 10))


def project_from_history(lineups: list[tuple[int, tuple[int, ...]]], active_player_ids: set[int]) -> tuple[int, ...]:
    """Project 1-9 using deterministic recency-weighted slot frequencies.

    `lineups` is newest-first `(game_pk, starting_nine)` history. The newest
    lineup receives weight N, then N-1 ... 1. Greedy assignment is slot ordered;
    ties prefer the player appearing more recently, then smaller MLBAM ID. This
    is frozen source logic, not fitted against outcomes.
    """
    if len(lineups) < MIN_LINEUPS:
        raise MLBSourceError("MLB_PROJECTED_LINEUP_INSUFFICIENT_HISTORY")
    use = lineups[:MAX_LINEUPS]
    scores: dict[int, dict[int, float]] = {s: {} for s in range(1, 10)}
    recency: dict[tuple[int, int], int] = {}
    n = len(use)
    for idx, (_gid, lineup) in enumerate(use):
        if len(lineup) != 9 or len(set(lineup)) != 9:
            raise MLBSourceError("MLB_PROJECTED_LINEUP_HISTORY_MALFORMED")
        weight = float(n - idx)
        for slot, pid in enumerate(lineup, start=1):
            if pid not in active_player_ids:
                continue
            scores[slot][pid] = scores[slot].get(pid, 0.0) + weight
            recency.setdefault((slot, pid), idx)
    selected: list[int] = []
    used: set[int] = set()
    for slot in range(1, 10):
        candidates = [
            (score, -recency[(slot, pid)], -pid, pid)
            for pid, score in scores[slot].items() if pid not in used
        ]
        if not candidates:
            raise MLBSourceError(f"MLB_PROJECTED_LINEUP_SLOT_UNRESOLVED:{slot}")
        pid = max(candidates)[3]
        selected.append(pid); used.add(pid)
    if len(selected) != 9 or len(set(selected)) != 9:
        raise MLBSourceError("MLB_PROJECTED_LINEUP_ASSIGNMENT_INVALID")
    return tuple(selected)


def _active_roster(team_id: int, opener: Callable = urlopen) -> set[int]:
    payload = _get_json(f"{BASE}/api/v1/teams/{int(team_id)}/roster?rosterType=active", opener)
    roster = payload.get("roster") or []
    ids: set[int] = set()
    for row in roster:
        person = (row or {}).get("person") or {}
        try:
            pid = int(person.get("id"))
        except (TypeError, ValueError):
            continue
        if pid > 0:
            ids.add(pid)
    if len(ids) < 9:
        raise MLBSourceError("MLB_ACTIVE_ROSTER_UNRESOLVED")
    return ids


def _finalize_projection(*, team_id: int, history: list[tuple[datetime, int, tuple[int, ...]]], active: set[int], now: datetime) -> ProjectedLineup:
    history.sort(key=lambda x: (x[0], x[1]), reverse=True)
    dedup: list[tuple[int, tuple[int, ...]]] = []
    dates: dict[int, str] = {}
    seen: set[int] = set()
    for dt, gid, nine in history:
        if gid in seen:
            continue
        seen.add(gid); dedup.append((gid, nine)); dates[gid] = dt.date().isoformat()
        if len(dedup) >= MAX_LINEUPS:
            break
    projected = project_from_history(dedup, active)
    return ProjectedLineup(
        team_id=int(team_id), player_ids=projected, batting_slots=tuple(range(1, 10)),
        source_game_pks=tuple(gid for gid, _ in dedup), latest_source_date=dates[dedup[0][0]],
        retrieved_at_utc=now.astimezone(timezone.utc).isoformat(),
    )


def build_slate_projections(*, team_ids: Iterable[int], slate_date: date, now: datetime, opener: Callable = urlopen, lookback_days: int = LOOKBACK_DAYS) -> tuple[dict[int, ProjectedLineup], dict[int, str]]:
    """Build projections for a slate with one shared historical scan.

    Returns `(projections, failures)` keyed by exact MLB team ID. All schedule
    dates queried are strictly before `slate_date`; current-day outcomes can never
    enter the projection. Boxscores are fetched at most once per historical game.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise MLBSourceError("NOW_TIMEZONE_REQUIRED")
    if lookback_days < 7 or lookback_days > 45:
        raise MLBSourceError("MLB_PROJECTED_LINEUP_LOOKBACK_INVALID")
    teams = sorted({int(x) for x in team_ids if int(x) > 0})
    if not teams:
        return {}, {}
    active: dict[int, set[int]] = {}
    failures: dict[int, str] = {}
    for tid in teams:
        try:
            active[tid] = _active_roster(tid, opener)
        except Exception as exc:
            failures[tid] = f"{type(exc).__name__}:{exc}"
    histories: dict[int, list[tuple[datetime, int, tuple[int, ...]]]] = {tid: [] for tid in teams if tid not in failures}
    target = set(histories)
    box_cache: dict[int, dict[str, Any]] = {}
    for delta in range(1, lookback_days + 1):
        if all(len(histories[tid]) >= MAX_LINEUPS for tid in histories):
            break
        d = slate_date - timedelta(days=delta)
        try:
            games = fetch_schedule(d.isoformat(), opener=opener, now=now)
        except Exception:
            continue
        for game in games:
            involved = target.intersection({int(game.away_id), int(game.home_id)})
            if not involved or game.status != "Final":
                continue
            try:
                box = box_cache.get(int(game.game_pk))
                if box is None:
                    box = fetch_boxscore(game.game_pk, opener=opener); box_cache[int(game.game_pk)] = box
                game_dt = parse_game_start(game.game_date)
            except Exception:
                continue
            for tid in involved:
                if len(histories[tid]) >= MAX_LINEUPS:
                    continue
                side = "away" if int(game.away_id) == tid else "home"
                try:
                    nine = _starting_nine(parse_confirmed_lineup(box, side))
                except Exception:
                    continue
                histories[tid].append((game_dt, int(game.game_pk), nine))
    out: dict[int, ProjectedLineup] = {}
    for tid, history in histories.items():
        try:
            out[tid] = _finalize_projection(team_id=tid, history=history, active=active[tid], now=now)
        except Exception as exc:
            failures[tid] = f"{type(exc).__name__}:{exc}"
    return out, failures


def build_team_projection(*, team_id: int, slate_date: date, now: datetime, opener: Callable = urlopen, lookback_days: int = LOOKBACK_DAYS) -> ProjectedLineup:
    projections, failures = build_slate_projections(team_ids=[team_id], slate_date=slate_date, now=now, opener=opener, lookback_days=lookback_days)
    if int(team_id) not in projections:
        raise MLBSourceError(failures.get(int(team_id), "MLB_PROJECTED_LINEUP_UNRESOLVED"))
    return projections[int(team_id)]
