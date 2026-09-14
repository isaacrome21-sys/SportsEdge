from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import exp, sqrt
import random
from typing import Any, Iterable, Mapping

from sportsedge.sports.cfb.prop_efficiency_engine import build_efficiency_distribution
from sportsedge.sports.cfb.prop_volume_stage1 import CFBVolumeStage1

from .football_joint import (
    PlayerRole,
    TeamEnvironment,
    _allocate,
    _binomial,
    _clamp,
    _history_index,
    _poisson,
    _ratio,
    _weighted,
)
from .sources.common import normalize_name, normalize_team
from .types import DKPlayer

MODEL_ID = "CFB_DFS_JOINT_PATHS_V1_RESEARCH"
STATUS = "RESEARCH_ONLY_UNVALIDATED_DFS_DISTRIBUTION"


def _team_environment(team: str, team_games: Mapping[tuple[str, int, int], Mapping[str, float]]) -> TeamEnvironment:
    rows = [
        (season, week, values)
        for (row_team, season, week), values in team_games.items()
        if normalize_team(row_team) == normalize_team(team)
    ]
    rows.sort(key=lambda item: (item[0], item[1]))
    rows = rows[-8:]
    pass_mean = _weighted([float(v["pass_attempts"]) for _, _, v in rows], decay=.78, default=31.0)
    rush_mean = _weighted([float(v["rush_attempts"]) for _, _, v in rows], decay=.78, default=37.0)
    pass_td = _weighted([float(v["pass_tds"]) for _, _, v in rows], decay=.78, default=1.85)
    rush_td = _weighted([float(v["rush_tds"]) for _, _, v in rows], decay=.78, default=1.55)
    return TeamEnvironment(
        team=normalize_team(team),
        pass_attempt_mean=_clamp(pass_mean, 14.0, 58.0),
        rush_attempt_mean=_clamp(rush_mean, 14.0, 62.0),
        pass_td_mean=_clamp(pass_td, .25, 5.5),
        rush_td_mean=_clamp(rush_td, .25, 5.0),
        field_goal_mean=1.35,
        history_games=len(rows),
    )


def _prior(position: str) -> dict[str, float]:
    pos = position.upper()
    if pos == "QB":
        return {"pass_share": .96, "carry_share": .18, "target_share": 0.0, "catch": 0.0,
                "ypt": 0.0, "ypc": 4.8, "pass_td_rate": .055, "rush_td_rate": .040,
                "rec_td_rate": 0.0, "int_rate": .024}
    if pos == "RB":
        return {"pass_share": 0.0, "carry_share": .40, "target_share": .11, "catch": .72,
                "ypt": 6.5, "ypc": 4.7, "pass_td_rate": 0.0, "rush_td_rate": .045,
                "rec_td_rate": .025, "int_rate": 0.0}
    if pos == "TE":
        return {"pass_share": 0.0, "carry_share": .003, "target_share": .13, "catch": .67,
                "ypt": 7.5, "ypc": 4.0, "pass_td_rate": 0.0, "rush_td_rate": .012,
                "rec_td_rate": .052, "int_rate": 0.0}
    return {"pass_share": 0.0, "carry_share": .025, "target_share": .20, "catch": .62,
            "ypt": 8.8, "ypc": 6.5, "pass_td_rate": 0.0, "rush_td_rate": .020,
            "rec_td_rate": .050, "int_rate": 0.0}


def _role(
    player: DKPlayer,
    *,
    history_rows: list[dict[str, Any]],
    team_env: TeamEnvironment,
    team_games: Mapping[tuple[str, int, int], Mapping[str, float]],
) -> PlayerRole:
    pos = player.positions[0] if player.positions else "WR"
    prior = _prior(pos)
    row_shares: dict[str, list[float]] = {"pass": [], "carry": [], "target": []}
    for row in history_rows:
        key = (normalize_team(row.get("team")), int(row.get("season", 0)), int(row.get("week", 0)))
        totals = team_games.get(key) or {}
        if float(totals.get("pass_attempts", 0.0)) > 0:
            row_shares["pass"].append(float(row.get("attempts", 0.0) or 0.0) / float(totals["pass_attempts"]))
        if float(totals.get("rush_attempts", 0.0)) > 0:
            row_shares["carry"].append(float(row.get("carries", 0.0) or 0.0) / float(totals["rush_attempts"]))
        if float(totals.get("targets", 0.0)) > 0:
            row_shares["target"].append(float(row.get("targets", 0.0) or 0.0) / float(totals["targets"]))
    pass_share = _clamp(_weighted(row_shares["pass"], decay=.78, default=prior["pass_share"]), 0.0, 1.0)
    carry_share = _clamp(_weighted(row_shares["carry"], decay=.78, default=prior["carry_share"]), 0.0, 1.0)
    target_share = _clamp(_weighted(row_shares["target"], decay=.78, default=prior["target_share"]), 0.0, 1.0)
    volume = CFBVolumeStage1()

    def volume_mean(metric: str, raw: str, team_mean: float, share: float) -> float:
        if not history_rows:
            return max(0.0, team_mean * share)
        hist = [{metric: float(row.get(raw, 0.0) or 0.0)} for row in history_rows]
        try:
            return volume.project(
                player_id=player.player_id,
                metric=metric,
                history=hist,
                team_opportunity_mean=max(team_mean, 1e-6),
                role_share=share,
            ).mean
        except Exception:
            return max(0.0, team_mean * share)

    catch_base = _ratio(history_rows, "receptions", "targets", prior["catch"], 9.0)
    ypt_base = _ratio(history_rows, "receiving_yards", "targets", prior["ypt"], 10.0)
    ypc_base = _ratio(history_rows, "rushing_yards", "carries", prior["ypc"], 12.0)
    catch = build_efficiency_distribution("catch_rate", {"baseline": catch_base, "uncertainty": .10}).mean
    ypt = build_efficiency_distribution("yards_per_target", {"baseline": ypt_base, "uncertainty": 2.0}).mean
    ypc = build_efficiency_distribution("yards_per_carry", {"baseline": ypc_base, "uncertainty": 1.5}).mean
    return PlayerRole(
        dk_player_id=player.player_id,
        name=player.name,
        team=normalize_team(player.team),
        position=pos,
        pass_attempt_mean=volume_mean("pass_attempts", "attempts", team_env.pass_attempt_mean, pass_share),
        carry_mean=volume_mean("rush_attempts", "carries", team_env.rush_attempt_mean, carry_share),
        target_mean=volume_mean("targets", "targets", team_env.pass_attempt_mean, target_share),
        catch_rate=_clamp(catch, .20, .96),
        yards_per_target=_clamp(ypt, 2.5, 16.0),
        yards_per_carry=_clamp(ypc, 1.5, 11.0),
        pass_td_rate=_clamp(_ratio(history_rows, "passing_tds", "attempts", prior["pass_td_rate"], 32.0), .004, .16),
        rush_td_rate=_clamp(_ratio(history_rows, "rushing_tds", "carries", prior["rush_td_rate"], 24.0), .002, .25),
        rec_td_rate=_clamp(_ratio(history_rows, "receiving_tds", "targets", prior["rec_td_rate"], 20.0), .002, .25),
        int_rate=_clamp(_ratio(history_rows, "interceptions", "attempts", prior["int_rate"], 35.0), .002, .10),
        fumble_lost_per_game=_clamp(_weighted([float(r.get("fumbles_lost", 0.0) or 0.0) for r in history_rows], decay=.78, default=.03), 0.0, .6),
        cold_start=not history_rows,
        history_games=len(history_rows),
    )


def build_cfb_joint_path_snapshot(
    *,
    players: Iterable[DKPlayer],
    history_payload: Mapping[str, Any],
    as_of: datetime,
    paths: int = 5000,
    seed: int = 20260914,
) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("CFB_DFS_AS_OF_TIMEZONE_REQUIRED")
    if paths < 1000:
        raise ValueError("CFB_DFS_PATH_COUNT_TOO_LOW")
    active = [p for p in players if not p.is_disabled]
    if not active:
        raise ValueError("CFB_DFS_ACTIVE_POOL_EMPTY")
    by_name, team_games = _history_index(history_payload)
    teams = sorted({normalize_team(p.team) for p in active if p.team})
    env = {team: _team_environment(team, team_games) for team in teams}
    roles: dict[str, PlayerRole] = {}
    for player in active:
        rows = by_name.get((normalize_team(player.team), normalize_name(player.name)), [])
        roles[player.player_id] = _role(player, history_rows=rows, team_env=env[normalize_team(player.team)], team_games=team_games)

    by_team: dict[str, list[DKPlayer]] = defaultdict(list)
    for player in active:
        by_team[normalize_team(player.team)].append(player)
    games: set[tuple[str, str]] = set()
    for player in active:
        team, opp = normalize_team(player.team), normalize_team(player.opponent)
        if team and opp and team != opp:
            games.add(tuple(sorted((team, opp))))
    if not games:
        raise ValueError("CFB_DFS_GAME_IDENTITY_MISSING")

    samples: dict[str, list[dict[str, float]]] = {p.player_id: [] for p in active}
    rng = random.Random(int(seed))
    for _ in range(int(paths)):
        for team_a, team_b in sorted(games):
            pace_sigma = .115
            pace = exp(rng.gauss(-.5 * pace_sigma * pace_sigma, pace_sigma))
            for team in (team_a, team_b):
                tenv = env.get(team) or TeamEnvironment(team, 31.0, 37.0, 1.85, 1.55, 1.35, 0)
                team_players = by_team.get(team, [])
                qbs = [p for p in team_players if "QB" in p.positions]
                skill = [p for p in team_players if bool(set(p.positions) & {"QB", "RB", "WR", "TE"})]
                catchers = [p for p in team_players if bool(set(p.positions) & {"RB", "WR", "TE"})]
                pass_attempts = max(6, _poisson(rng, tenv.pass_attempt_mean * pace))
                rush_attempts = max(7, _poisson(rng, tenv.rush_attempt_mean * pace))
                pass_tds = _poisson(rng, tenv.pass_td_mean * pace)
                rush_tds = _poisson(rng, tenv.rush_td_mean * pace)

                def noisy_weight(player: DKPlayer, base: float) -> float:
                    role = roles[player.player_id]
                    sigma = .16 + (.12 if role.cold_start else 0.0)
                    return max(1e-6, base * exp(rng.gauss(-.5 * sigma * sigma, sigma)))

                qb_counts = _allocate(rng, pass_attempts, qbs, [noisy_weight(p, roles[p.player_id].pass_attempt_mean) for p in qbs])
                carry_counts = _allocate(rng, rush_attempts, skill, [noisy_weight(p, roles[p.player_id].carry_mean) for p in skill])
                target_counts = _allocate(rng, pass_attempts, catchers, [noisy_weight(p, roles[p.player_id].target_mean) for p in catchers])
                qb_td_counts = _allocate(rng, pass_tds, qbs, [max(1e-5, qb_counts.get(p.player_id, 0)) for p in qbs])
                rec_td_counts = _allocate(
                    rng, pass_tds, catchers,
                    [max(1e-5, target_counts.get(p.player_id, 0) * roles[p.player_id].rec_td_rate) for p in catchers],
                )
                rush_td_counts = _allocate(
                    rng, rush_tds, skill,
                    [max(1e-5, carry_counts.get(p.player_id, 0) * roles[p.player_id].rush_td_rate) for p in skill],
                )

                rows: dict[str, dict[str, float]] = {}
                team_rec_yards = 0.0
                for player in team_players:
                    role = roles[player.player_id]
                    carries = carry_counts.get(player.player_id, 0)
                    targets = target_counts.get(player.player_id, 0)
                    receptions = _binomial(rng, targets, role.catch_rate) if targets else 0
                    rush_yards = max(0.0, rng.gauss(carries * role.yards_per_carry, sqrt(max(carries, 1)) * 2.5)) if carries else 0.0
                    rec_yards = max(0.0, rng.gauss(targets * role.yards_per_target, sqrt(max(targets, 1)) * 3.7)) if targets else 0.0
                    team_rec_yards += rec_yards
                    row = {
                        "receptions": float(receptions),
                        "rec_yards": rec_yards,
                        "rec_tds": float(rec_td_counts.get(player.player_id, 0)),
                        "rush_yards": rush_yards,
                        "rush_tds": float(rush_td_counts.get(player.player_id, 0)),
                        "fumbles_lost": 1.0 if rng.random() < min(.70, role.fumble_lost_per_game) else 0.0,
                    }
                    if "QB" in player.positions:
                        attempts = qb_counts.get(player.player_id, 0)
                        row.update({
                            "pass_yards": 0.0,
                            "pass_tds": float(qb_td_counts.get(player.player_id, 0)),
                            "interceptions": float(_binomial(rng, attempts, role.int_rate)),
                        })
                    rows[player.player_id] = row
                total_qb_attempts = sum(qb_counts.values())
                for qb in qbs:
                    if qb.player_id in rows:
                        rows[qb.player_id]["pass_yards"] = team_rec_yards * qb_counts.get(qb.player_id, 0) / max(total_qb_attempts, 1)
                for pid, row in rows.items():
                    samples[pid].append(row)

    if any(len(rows) != paths for rows in samples.values()):
        bad = {pid: len(rows) for pid, rows in samples.items() if len(rows) != paths}
        raise ValueError("CFB_DFS_PATH_ALIGNMENT_FAILED:" + json.dumps(bad, sort_keys=True))
    cold = [role for role in roles.values() if role.cold_start]
    identity = {
        "model_id": MODEL_ID,
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "paths": int(paths),
        "seed": int(seed),
        "history_manifest_sha": history_payload.get("source_manifest_sha256"),
        "players": sorted((p.player_id, p.name, p.team) for p in active),
    }
    path_set_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1,
        "sport": "CFB",
        "model_id": MODEL_ID,
        "status": STATUS,
        "updated_at": as_of.astimezone(timezone.utc).isoformat(),
        "source": "SPORTSEDGE_CFB_ESPN_PIT_VOLUME_EFFICIENCY_JOINT_SIM",
        "path_set_id": path_set_id,
        "path_count": int(paths),
        "seed": int(seed),
        "history_source": {
            "source": history_payload.get("source"),
            "source_manifest_sha256": history_payload.get("source_manifest_sha256"),
            "provenance_mode": history_payload.get("provenance_mode"),
            "targets_estimated_rows": history_payload.get("targets_estimated_rows"),
        },
        "diagnostics": {
            "active_player_count": len(active),
            "cold_start_player_count": len(cold),
            "cold_start_rate": len(cold) / max(1, len(active)),
            "team_history_games": {team: tenv.history_games for team, tenv in env.items()},
            "validation_status": "UNVALIDATED_RESEARCH_ONLY",
            "cfb_role_volatility_enabled": True,
        },
        "players": [
            {
                "player_id": player.player_id,
                "name": player.name,
                "team": player.team,
                "source": "SPORTSEDGE_CFB_JOINT_PATHS",
                "updated_at": as_of.astimezone(timezone.utc).isoformat(),
                "path_set_id": path_set_id,
                "samples": samples[player.player_id],
            }
            for player in active
        ],
    }
