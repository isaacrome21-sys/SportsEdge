#!/usr/bin/env python3
"""SportsEdge schedule-relative completeness gate v0.3.

This module intentionally layers on v0.2 without modifying the frozen v0.2
source. Completeness is derived from an explicitly complete authoritative
schedule snapshot for the requested slate date; it is never inferred from a
filtered feature/odds/model table and never assumes all 30 clubs play.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from sportsedge_foundation_v0_2 import canonical_team_id
except ImportError:
    from .sportsedge_foundation_v0_2 import canonical_team_id

ACTIVE_PREGAME_STATUSES = {
    "scheduled", "pre-game", "pregame", "warmup", "delayed", "in progress"
}

@dataclass(frozen=True)
class ScheduleExpectation:
    slate_date: str
    source_id: str
    expected_game_ids: Tuple[str, ...]
    expected_team_appearances: Tuple[Tuple[str, str], ...]
    expected_unique_teams: Tuple[str, ...]

def _cid(row: Dict[str, Any], prefix: str) -> Optional[str]:
    return canonical_team_id(
        row.get(f"{prefix}_full") or row.get(f"{prefix}_team"),
        row.get(f"{prefix}_short"),
    )

def derive_schedule_expectation(schedule_snapshot: Dict[str, Any]) -> ScheduleExpectation:
    if schedule_snapshot.get("source_kind") != "AUTHORITATIVE_SCHEDULE":
        raise ValueError("schedule source_kind must be AUTHORITATIVE_SCHEDULE")
    if schedule_snapshot.get("is_complete_day_snapshot") is not True:
        raise ValueError("schedule snapshot completeness is not explicitly attested")
    slate_date = str(schedule_snapshot.get("slate_date") or "").strip()
    source_id = str(schedule_snapshot.get("source_id") or "").strip()
    if not slate_date or not source_id:
        raise ValueError("schedule snapshot requires slate_date and source_id")
    games = schedule_snapshot.get("games")
    if not isinstance(games, list):
        raise ValueError("schedule games must be a list")

    game_ids: List[str] = []
    appearances: List[Tuple[str, str]] = []
    seen_ids: Set[str] = set()
    for g in games:
        gid = str(g.get("game_id") or "").strip()
        if not gid:
            raise ValueError("every schedule game requires stable game_id")
        if gid in seen_ids:
            raise ValueError(f"duplicate schedule game_id: {gid}")
        seen_ids.add(gid)
        status = str(g.get("status") or "scheduled").strip().lower()
        if status not in ACTIVE_PREGAME_STATUSES:
            continue
        away = _cid(g, "away")
        home = _cid(g, "home")
        if not away or not home:
            raise ValueError(f"unresolved team identity in authoritative schedule game {gid}")
        game_ids.append(gid)
        appearances.append((gid, away))
        appearances.append((gid, home))

    unique = sorted({team for _, team in appearances})
    return ScheduleExpectation(
        slate_date=slate_date,
        source_id=source_id,
        expected_game_ids=tuple(game_ids),
        expected_team_appearances=tuple(appearances),
        expected_unique_teams=tuple(unique),
    )

def schedule_relative_coverage_check(raw_rows: List[Dict[str, Any]], schedule_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    exp = derive_schedule_expectation(schedule_snapshot)
    raw_games: Set[str] = set()
    raw_appearances: Set[Tuple[str, str]] = set()
    unresolved: List[Dict[str, Any]] = []
    duplicate_game_rows: List[str] = []

    for row in raw_rows:
        gid = str(row.get("game_id") or "").strip()
        if not gid:
            unresolved.append({"reason": "MISSING_GAME_ID", "row": row})
            continue
        if gid in raw_games:
            duplicate_game_rows.append(gid)
        raw_games.add(gid)
        for prefix in ("away", "home"):
            team = _cid(row, prefix)
            if team:
                raw_appearances.add((gid, team))
            else:
                unresolved.append({
                    "reason": "UNRESOLVED_TEAM",
                    "game_id": gid,
                    "side": prefix,
                    "raw": row.get(f"{prefix}_full") or row.get(f"{prefix}_team") or row.get(f"{prefix}_short"),
                })

    expected_games = set(exp.expected_game_ids)
    expected_apps = set(exp.expected_team_appearances)
    missing_games = sorted(expected_games - raw_games)
    unexpected_games = sorted(raw_games - expected_games)
    missing_apps = sorted(expected_apps - raw_appearances)
    unexpected_apps = sorted(raw_appearances - expected_apps)
    passed = not (missing_games or unexpected_games or missing_apps or unexpected_apps or unresolved or duplicate_game_rows)
    return {
        "status": "PASS" if passed else "FAIL_CLOSED",
        "pass": passed,
        "checked_on": "RAW rows against complete authoritative schedule snapshot",
        "slate_date": exp.slate_date,
        "schedule_source_id": exp.source_id,
        "expected_games": len(exp.expected_game_ids),
        "observed_games": len(raw_games),
        "expected_team_appearances": len(exp.expected_team_appearances),
        "observed_team_appearances": len(raw_appearances),
        "expected_unique_teams": len(exp.expected_unique_teams),
        "missing_game_ids": missing_games,
        "unexpected_game_ids": unexpected_games,
        "missing_team_appearances": missing_apps,
        "unexpected_team_appearances": unexpected_apps,
        "duplicate_game_rows": sorted(set(duplicate_game_rows)),
        "unresolved": unresolved,
        "expected": asdict(exp),
    }
