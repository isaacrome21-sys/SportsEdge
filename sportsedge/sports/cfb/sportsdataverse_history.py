"""Leakage-resistant SportsDataverse CFB history normalization.

This module is selection/training plumbing only. It creates no PIT evidence,
Model_P, promotion, staking, Truth Gate, or OFFICIAL authority.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Any

SOURCE_CONTRACT = "SPORTSDATAVERSE_ESPN_CFB_ADV_V1|RECONSTRUCTED_PRIOR_WEEK_V1"
ALLOWED_DATASETS = frozenset({
    "espn_cfb_schedules", "espn_cfb_adv_team", "espn_cfb_adv_drives",
    "espn_cfb_adv_situational", "espn_cfb_team_box",
})
PROHIBITED_DATASETS = frozenset({"espn_cfb_betting"})
MARKET_COLUMNS = frozenset({
    "game_spread", "over_under", "home_favorite", "home_team_spread",
    "game_spread_available", "odds_source",
})


class SportsDataverseHistoryError(ValueError):
    pass


@dataclass(frozen=True)
class TeamSnapshot:
    team_id: int
    season: int
    through_week: int
    games_in_sample: int
    off_ppa_rush: float
    off_ppa_dropback: float
    off_success_rate: float
    standard_down_ppa: float
    passing_down_success_rate: float
    explosive_rate: float
    net_field_position: float
    source_contract: str = SOURCE_CONTRACT


def validate_dataset(dataset: str, rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if dataset in PROHIBITED_DATASETS:
        raise SportsDataverseHistoryError(f"CFB_SDV_PROHIBITED_DATASET:{dataset}")
    if dataset not in ALLOWED_DATASETS:
        raise SportsDataverseHistoryError(f"CFB_SDV_UNREGISTERED_DATASET:{dataset}")
    out = list(rows)
    for row in out:
        leaked = MARKET_COLUMNS.intersection(row)
        if leaked:
            raise SportsDataverseHistoryError(
                "CFB_SDV_MARKET_COLUMN_PROHIBITED:" + ",".join(sorted(leaked))
            )
        season = row.get("season")
        if season is not None and int(season) >= 2026:
            raise SportsDataverseHistoryError("CFB_SDV_2026_OUTCOME_ROWS_PROHIBITED")
    return out


def attach_drive_time(
    drive_rows: Iterable[Mapping[str, Any]],
    schedule_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach season/week to adv_drives by game_id; fail closed on ambiguity."""
    schedule_index: dict[int, tuple[int, int]] = {}
    for row in schedule_rows:
        game_id = int(row["game_id"])
        stamp = (int(row["season"]), int(row["week"]))
        prior = schedule_index.get(game_id)
        if prior is not None and prior != stamp:
            raise SportsDataverseHistoryError(f"CFB_SDV_AMBIGUOUS_GAME_TIME:{game_id}")
        schedule_index[game_id] = stamp
    out = []
    for row in drive_rows:
        game_id = int(row["game_id"])
        if game_id not in schedule_index:
            raise SportsDataverseHistoryError(f"CFB_SDV_DRIVE_TIME_MISSING:{game_id}")
        season, week = schedule_index[game_id]
        if row.get("season") is not None and int(row["season"]) != season:
            raise SportsDataverseHistoryError(f"CFB_SDV_DRIVE_SEASON_MISMATCH:{game_id}")
        out.append({**row, "season": season, "week": week})
    return out


def _mean(rows: list[Mapping[str, Any]], key: str) -> float:
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    if not vals:
        raise SportsDataverseHistoryError(f"CFB_SDV_REQUIRED_METRIC_MISSING:{key}")
    return sum(vals) / len(vals)


def build_team_snapshots(
    *,
    adv_team_rows: Iterable[Mapping[str, Any]],
    adv_situational_rows: Iterable[Mapping[str, Any]],
    adv_drive_rows: Iterable[Mapping[str, Any]],
    schedule_rows: Iterable[Mapping[str, Any]],
    target_season: int,
    target_week: int,
) -> list[TeamSnapshot]:
    """Aggregate only games known before target_week.

    Rows from target_week or later are excluded. 2026 realized rows are rejected
    by contract rather than silently filtered.
    """
    if target_season >= 2026:
        raise SportsDataverseHistoryError("CFB_SDV_TARGET_OUTCOME_SEASON_PROHIBITED")
    schedules = validate_dataset("espn_cfb_schedules", schedule_rows)
    team = validate_dataset("espn_cfb_adv_team", adv_team_rows)
    situ = validate_dataset("espn_cfb_adv_situational", adv_situational_rows)
    drives = validate_dataset("espn_cfb_adv_drives", adv_drive_rows)
    drives = attach_drive_time(drives, schedules)

    def eligible(r: Mapping[str, Any]) -> bool:
        return int(r["season"]) == target_season and int(r["week"]) < target_week

    team = [r for r in team if eligible(r)]
    situ = [r for r in situ if eligible(r)]
    drives = [r for r in drives if eligible(r)]

    tg: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    sg: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    dg: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for r in team: tg[int(r["pos_team"])].append(r)
    for r in situ: sg[int(r["pos_team"])].append(r)
    for r in drives: dg[int(r["pos_team"])].append(r)

    snapshots = []
    for team_id in sorted(tg):
        t, s, d = tg[team_id], sg.get(team_id, []), dg.get(team_id, [])
        if not s or not d:
            raise SportsDataverseHistoryError(f"CFB_SDV_JOIN_COVERAGE_MISSING:{team_id}")
        game_ids = {int(r["game_id"]) for r in t}
        if {int(r["game_id"]) for r in s} != game_ids or {int(r["game_id"]) for r in d} != game_ids:
            raise SportsDataverseHistoryError(f"CFB_SDV_JOIN_COVERAGE_MISMATCH:{team_id}")
        snapshots.append(TeamSnapshot(
            team_id=team_id,
            season=target_season,
            through_week=target_week - 1,
            games_in_sample=len(game_ids),
            off_ppa_rush=_mean(t, "EPA_rushing_per_play"),
            off_ppa_dropback=_mean(t, "EPA_passing_per_play"),
            off_success_rate=_mean(s, "EPA_success_rate"),
            standard_down_ppa=_mean(s, "EPA_standard_down_per_play"),
            passing_down_success_rate=_mean(s, "EPA_success_passing_down_rate"),
            explosive_rate=_mean(t, "EPA_explosive_rate"),
            net_field_position=-_mean(d, "avg_field_position"),
        ))
    return snapshots
