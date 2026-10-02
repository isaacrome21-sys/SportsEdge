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
    "cfb_schedules", "espn_cfb_adv_team", "espn_cfb_adv_drives",
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
    def_ppa_rush_allowed: float
    def_ppa_dropback_allowed: float
    def_success_rate_allowed: float
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


def regular_fbs_schedule_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return only frozen regular-season FBS-vs-FBS games using upstream scope flags."""
    out=[]
    for row in validate_dataset("cfb_schedules", rows):
        if "season_type" not in row:
            raise SportsDataverseHistoryError("CFB_SDV_SEASON_TYPE_REQUIRED")
        if "fbs_game" not in row or row["fbs_game"] is None:
            raise SportsDataverseHistoryError("CFB_SDV_FBS_GAME_FLAG_REQUIRED")
        season_type=str(row["season_type"]).strip().lower()
        if season_type not in {"regular","2"}:
            continue
        raw=row["fbs_game"]
        token = str(raw).strip().lower()
        if raw is True or token in {"true","1","t"}:
            out.append(row)
        elif raw is False or token in {"false","0","f"}:
            continue
        else:
            raise SportsDataverseHistoryError("CFB_SDV_FBS_GAME_FLAG_INVALID:"+token)
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
    schedules = regular_fbs_schedule_rows(schedule_rows)
    allowed_game_ids = {int(r["game_id"]) for r in schedules}
    team = validate_dataset("espn_cfb_adv_team", adv_team_rows)
    situ = validate_dataset("espn_cfb_adv_situational", adv_situational_rows)
    drives = validate_dataset("espn_cfb_adv_drives", adv_drive_rows)
    all_schedule_ids = {int(r["game_id"]) for r in validate_dataset("cfb_schedules", schedule_rows)}
    observed_ids = {int(r["game_id"]) for r in team + situ + drives}
    unknown_ids = sorted(observed_ids - all_schedule_ids)
    if unknown_ids:
        raise SportsDataverseHistoryError("CFB_SDV_ADV_GAME_MISSING_SCHEDULE:"+",".join(map(str,unknown_ids[:20])))
    drives = [r for r in drives if int(r["game_id"]) in allowed_game_ids]
    drives = attach_drive_time(drives, schedules)

    def in_scope(r: Mapping[str, Any]) -> bool:
        return int(r["game_id"]) in allowed_game_ids

    team = [r for r in team if in_scope(r)]
    situ = [r for r in situ if in_scope(r)]
    drives = [r for r in drives if in_scope(r)]

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

    # Defensive EPA/success allowed is defined from the opponent offense in the
    # same game. This preserves the exact upstream EPA semantics instead of
    # relabeling adv_defensive havoc/tackle fields as EPA allowed.
    opponent_by_game_team: dict[tuple[int, int], Mapping[str, Any]] = {}
    situ_by_game_team: dict[tuple[int, int], Mapping[str, Any]] = {}
    for r in team:
        opponent_by_game_team[(int(r["game_id"]), int(r["pos_team"]))] = r
    for r in situ:
        situ_by_game_team[(int(r["game_id"]), int(r["pos_team"]))] = r

    snapshots = []
    for team_id in sorted(tg):
        t, s, d = tg[team_id], sg.get(team_id, []), dg.get(team_id, [])
        if not s or not d:
            raise SportsDataverseHistoryError(f"CFB_SDV_JOIN_COVERAGE_MISSING:{team_id}")
        game_ids = {int(r["game_id"]) for r in t}
        if {int(r["game_id"]) for r in s} != game_ids or {int(r["game_id"]) for r in d} != game_ids:
            raise SportsDataverseHistoryError(f"CFB_SDV_JOIN_COVERAGE_MISMATCH:{team_id}")
        opp_team_rows = []
        opp_situ_rows = []
        for row in t:
            game_id = int(row["game_id"])
            opponents = [x for (gid, tid), x in opponent_by_game_team.items()
                         if gid == game_id and tid != team_id]
            opp_situ = [x for (gid, tid), x in situ_by_game_team.items()
                        if gid == game_id and tid != team_id]
            if len(opponents) != 1 or len(opp_situ) != 1:
                raise SportsDataverseHistoryError(f"CFB_SDV_OPPONENT_JOIN_MISMATCH:{game_id}:{team_id}")
            opp_team_rows.extend(opponents)
            opp_situ_rows.extend(opp_situ)
        snapshots.append(TeamSnapshot(
            team_id=team_id,
            season=target_season,
            through_week=target_week - 1,
            games_in_sample=len(game_ids),
            off_ppa_rush=_mean(t, "EPA_rushing_per_play"),
            off_ppa_dropback=_mean(t, "EPA_passing_per_play"),
            off_success_rate=_mean(s, "EPA_success_rate"),
            def_ppa_rush_allowed=_mean(opp_team_rows, "EPA_rushing_per_play"),
            def_ppa_dropback_allowed=_mean(opp_team_rows, "EPA_passing_per_play"),
            def_success_rate_allowed=_mean(opp_situ_rows, "EPA_success_rate"),
            standard_down_ppa=_mean(s, "EPA_standard_down_per_play"),
            passing_down_success_rate=_mean(s, "EPA_success_passing_down_rate"),
            explosive_rate=_mean(t, "EPA_explosive_rate"),
            net_field_position=-_mean(d, "avg_field_position"),
        ))
    return snapshots


def build_season_week_snapshots(
    *,
    adv_team_rows: Iterable[Mapping[str, Any]],
    adv_situational_rows: Iterable[Mapping[str, Any]],
    adv_drive_rows: Iterable[Mapping[str, Any]],
    schedule_rows: Iterable[Mapping[str, Any]],
    season: int,
) -> list[TeamSnapshot]:
    """Materialize every available pregame weekly snapshot for one historical season.

    Snapshot for target week W contains only games from weeks < W. Empty week-1
    current-season state is intentionally omitted; callers must use the separately
    frozen prior-season fallback policy.
    """
    if not 2015 <= int(season) <= 2025:
        raise SportsDataverseHistoryError("CFB_SDV_SEASON_OUTSIDE_FROZEN_WINDOW")
    schedules = regular_fbs_schedule_rows(schedule_rows)
    season_weeks = sorted({
        int(r["week"]) for r in schedules
        if int(r["season"]) == int(season) and int(r["week"]) >= 1
    })
    out: list[TeamSnapshot] = []
    for target_week in season_weeks:
        if target_week <= 1:
            continue
        out.extend(build_team_snapshots(
            adv_team_rows=adv_team_rows,
            adv_situational_rows=adv_situational_rows,
            adv_drive_rows=adv_drive_rows,
            schedule_rows=schedules,
            target_season=int(season),
            target_week=target_week,
        ))
    keys=[(x.team_id,x.season,x.through_week) for x in out]
    if len(keys) != len(set(keys)):
        raise SportsDataverseHistoryError("CFB_SDV_WEEKLY_SNAPSHOT_DUPLICATE")
    return sorted(out,key=lambda x:(x.season,x.through_week,x.team_id))


def build_prior_season_fallback_snapshots(
    *,
    adv_team_rows: Iterable[Mapping[str, Any]],
    adv_situational_rows: Iterable[Mapping[str, Any]],
    adv_drive_rows: Iterable[Mapping[str, Any]],
    schedule_rows: Iterable[Mapping[str, Any]],
    target_season: int,
) -> list[TeamSnapshot]:
    """Build one prior-season fallback snapshot per team for target_season week 1."""
    prior=int(target_season)-1
    if not 2015 <= prior <= 2025 or not 2016 <= int(target_season) <= 2026:
        raise SportsDataverseHistoryError("CFB_SDV_PRIOR_FALLBACK_OUTSIDE_WINDOW")
    schedules=regular_fbs_schedule_rows(schedule_rows)
    weeks=[int(r["week"]) for r in schedules if int(r["season"])==prior]
    if not weeks:
        raise SportsDataverseHistoryError(f"CFB_SDV_PRIOR_FALLBACK_SEASON_EMPTY:{prior}")
    # target_week is one past the largest observed week, therefore every prior
    # season game is strictly earlier than the synthetic cutoff.
    snaps=build_team_snapshots(
        adv_team_rows=adv_team_rows,
        adv_situational_rows=adv_situational_rows,
        adv_drive_rows=adv_drive_rows,
        schedule_rows=schedules,
        target_season=prior,
        target_week=max(weeks)+1,
    )
    return sorted(snaps,key=lambda x:x.team_id)
