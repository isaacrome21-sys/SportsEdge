"""Deterministic early batting-order projection from official MLB prior lineups.

This is an identity/source bridge for pregame inference, not a betting model.
It uses only completed MLB games strictly before the current slate date plus the
current active roster. It never consumes sportsbook prices, current-game results,
or third-party projected lineups.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .mlb_source import BASE, MLBSourceError, _get_json, fetch_boxscore, fetch_schedule, parse_confirmed_lineup, parse_game_start

SOURCE = "MLB_STATSAPI_PRIOR_CONFIRMED_LINEUPS"
LOOKBACK_DAYS = 14
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
        return self.player_ids[0], self.player_ids[1], self.player_ids[2]


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


def _active_roster(team_id: int, opener: Callable = urlopen) -> set[int]:
    payload = _get_json(f"{BASE}/api/v1/teams/{int(team_id)}/roster?rosterType=active", opener)
    ids: set[int] = set()
    for row in payload.get("roster") or []:
        person = (row or {}).get("person") or {}
        try: pid = int(person.get("id"))
        except (TypeError, ValueError): continue
        if pid > 0: ids.add(pid)
    if len(ids) < 9:
        raise MLBSourceError("MLB_ACTIVE_ROSTER_UNRESOLVED")
    return ids


def project_from_history(lineups: list[tuple[int, tuple[int, ...]]], active_player_ids: set[int]) -> tuple[int, ...]:
    """Maximum-weight unique 1-9 assignment using fixed recency weights."""
    if len(lineups) < MIN_LINEUPS:
        raise MLBSourceError("MLB_PROJECTED_LINEUP_INSUFFICIENT_HISTORY")
    use = lineups[:MAX_LINEUPS]
    n = len(use)
    scores: dict[int, dict[int, float]] = {s: {} for s in range(1, 10)}
    latest: dict[int, int] = {}
    for idx, (_gid, nine) in enumerate(use):
        if len(nine) != 9 or len(set(nine)) != 9:
            raise MLBSourceError("MLB_PROJECTED_LINEUP_HISTORY_MALFORMED")
        weight = float(n - idx)
        for slot, pid in enumerate(nine, start=1):
            if pid not in active_player_ids:
                continue
            scores[slot][pid] = scores[slot].get(pid, 0.0) + weight
            latest[pid] = min(latest.get(pid, idx), idx)
    if any(not scores[s] for s in range(1, 10)):
        raise MLBSourceError("MLB_PROJECTED_LINEUP_ACTIVE_SLOT_EMPTY")

    # Deterministic dynamic-programming assignment. Candidate pools are naturally
    # small (recent starting lineups), so this avoids greedy duplicate-player
    # failures when a hitter has moved between batting slots.
    candidates = {s: tuple(sorted(scores[s], key=lambda p: (-scores[s][p], latest[p], p))) for s in range(1, 10)}

    @lru_cache(maxsize=None)
    def solve(slot: int, used: tuple[int, ...]):
        if slot == 10:
            return 0.0, ()
        used_set = set(used)
        best = None
        for pid in candidates[slot]:
            if pid in used_set:
                continue
            tail = solve(slot + 1, tuple(sorted((*used, pid))))
            if tail is None:
                continue
            score = scores[slot][pid] + tail[0]
            # Score first; then prefer more recent players and smaller IDs for a
            # deterministic tie break independent of dict/set iteration order.
            tie = (-latest[pid], -pid)
            candidate = (score, tie, (pid,) + tail[1])
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        if best is None:
            return None
        return best[0], best[2]

    solved = solve(1, ())
    if solved is None or len(solved[1]) != 9 or len(set(solved[1])) != 9:
        raise MLBSourceError("MLB_PROJECTED_LINEUP_ASSIGNMENT_UNRESOLVED")
    return tuple(int(x) for x in solved[1])


def build_slate_projections(*, team_ids: Iterable[int], slate_date: date, now: datetime, opener: Callable = urlopen, lookback_days: int = LOOKBACK_DAYS) -> tuple[dict[int, ProjectedLineup], dict[int, str]]:
    """Build projections for all requested teams while batching historical dates."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise MLBSourceError("NOW_TIMEZONE_REQUIRED")
    if not 7 <= int(lookback_days) <= 30:
        raise MLBSourceError("MLB_PROJECTED_LINEUP_LOOKBACK_INVALID")
    teams = tuple(sorted({int(t) for t in team_ids if int(t) > 0}))
    active: dict[int, set[int]] = {}
    failures: dict[int, str] = {}
    for tid in teams:
        try: active[tid] = _active_roster(tid, opener)
        except Exception as exc: failures[tid] = f"{type(exc).__name__}:{exc}"

    history: dict[int, list[tuple[datetime, int, tuple[int, ...]]]] = {t: [] for t in teams if t in active}
    seen_game: set[int] = set()
    for delta in range(1, int(lookback_days) + 1):
        day = slate_date - timedelta(days=delta)
        try: games = fetch_schedule(day.isoformat(), opener=opener, now=now)
        except Exception: continue
        for game in games:
            relevant = [t for t in (game.away_id, game.home_id) if t in history]
            if not relevant or game.status != "Final" or int(game.game_pk) in seen_game:
                continue
            seen_game.add(int(game.game_pk))
            try: box = fetch_boxscore(game.game_pk, opener=opener)
            except Exception: continue
            game_dt = parse_game_start(game.game_date)
            for side, tid in (("away", game.away_id), ("home", game.home_id)):
                if tid not in history:
                    continue
                try: nine = _starting_nine(parse_confirmed_lineup(box, side))
                except Exception: continue
                history[tid].append((game_dt, int(game.game_pk), nine))
        if history and all(len(v) >= MAX_LINEUPS for v in history.values()):
            break

    out: dict[int, ProjectedLineup] = {}
    for tid in teams:
        if tid not in active:
            continue
        rows = sorted(history.get(tid) or [], key=lambda x: (x[0], x[1]), reverse=True)
        dedup: list[tuple[int, tuple[int, ...]]] = []
        dates: dict[int, str] = {}
        used_gid: set[int] = set()
        for dt, gid, nine in rows:
            if gid in used_gid:
                continue
            used_gid.add(gid); dedup.append((gid, nine)); dates[gid] = dt.date().isoformat()
            if len(dedup) >= MAX_LINEUPS:
                break
        try:
            projected = project_from_history(dedup, active[tid])
            out[tid] = ProjectedLineup(
                team_id=tid,
                player_ids=projected,
                batting_slots=tuple(range(1, 10)),
                source_game_pks=tuple(g for g, _ in dedup),
                latest_source_date=dates[dedup[0][0]],
                retrieved_at_utc=now.astimezone(timezone.utc).isoformat(),
            )
        except Exception as exc:
            failures[tid] = f"{type(exc).__name__}:{exc}"
    return out, failures
