from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import exp, sqrt
import random
from statistics import fmean
from typing import Any, Iterable, Mapping

from sportsedge.sports.nfl.prop_efficiency_engine import build_efficiency_distribution
from sportsedge.sports.nfl.prop_volume_stage1 import NFLVolumeStage1

from .sources.common import normalize_name
from .types import DKPlayer

MODEL_ID = "NFL_DFS_JOINT_PATHS_V1_RESEARCH"
STATUS = "RESEARCH_ONLY_UNVALIDATED_DFS_DISTRIBUTION"
_TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}


@dataclass(frozen=True)
class PlayerRole:
    dk_player_id: str
    name: str
    team: str
    position: str
    pass_attempt_mean: float
    carry_mean: float
    target_mean: float
    catch_rate: float
    yards_per_target: float
    yards_per_carry: float
    pass_td_rate: float
    rush_td_rate: float
    rec_td_rate: float
    int_rate: float
    fumble_lost_per_game: float
    cold_start: bool
    history_games: int


@dataclass(frozen=True)
class TeamEnvironment:
    team: str
    pass_attempt_mean: float
    rush_attempt_mean: float
    pass_td_mean: float
    rush_td_mean: float
    field_goal_mean: float
    history_games: int


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(raw, raw)


def _weighted(values: list[float], *, decay: float = 0.82, default: float) -> float:
    if not values:
        return float(default)
    weights = [decay ** (len(values) - 1 - i) for i in range(len(values))]
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def _ratio(rows: Iterable[Mapping[str, Any]], numerator: str, denominator: str, prior: float, prior_n: float) -> float:
    num = 0.0
    den = 0.0
    for row in rows:
        num += max(0.0, float(row.get(numerator, 0.0) or 0.0))
        den += max(0.0, float(row.get(denominator, 0.0) or 0.0))
    return (num + prior * prior_n) / max(den + prior_n, 1e-9)


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, float(value)))


def _poisson(rng: random.Random, mean: float) -> int:
    lam = max(0.0, float(mean))
    if lam <= 0.0:
        return 0
    if lam >= 18.0:
        return max(0, int(round(rng.gauss(lam, sqrt(lam)))))
    threshold = exp(-lam)
    product = 1.0
    k = 0
    while product > threshold:
        k += 1
        product *= rng.random()
    return k - 1


def _binomial(rng: random.Random, n: int, p: float) -> int:
    trials = max(0, int(n))
    prob = _clamp(p, 0.0, 1.0)
    if trials == 0 or prob == 0.0:
        return 0
    if prob == 1.0:
        return trials
    if trials >= 25:
        mean = trials * prob
        var = trials * prob * (1.0 - prob)
        return min(trials, max(0, int(round(rng.gauss(mean, sqrt(max(var, 1e-9)))))))
    return sum(1 for _ in range(trials) if rng.random() < prob)


def _allocate(rng: random.Random, total: int, players: list[DKPlayer], weights: list[float]) -> dict[str, int]:
    if total <= 0:
        return {p.player_id: 0 for p in players}
    positive = [max(0.0, float(w)) for w in weights]
    if not players or sum(positive) <= 0:
        return {}
    picks = rng.choices([p.player_id for p in players], weights=positive, k=int(total))
    out = {p.player_id: 0 for p in players}
    for pid in picks:
        out[pid] += 1
    return out


def _dst_points(*, sacks: int, interceptions: int, fumble_recoveries: int, touchdowns: int,
                safeties: int, blocked_kicks: int, points_allowed: int) -> float:
    if points_allowed <= 0:
        pa = 10.0
    elif points_allowed <= 6:
        pa = 7.0
    elif points_allowed <= 13:
        pa = 4.0
    elif points_allowed <= 20:
        pa = 1.0
    elif points_allowed <= 27:
        pa = 0.0
    elif points_allowed <= 34:
        pa = -1.0
    else:
        pa = -4.0
    return (
        sacks
        + 2.0 * interceptions
        + 2.0 * fumble_recoveries
        + 6.0 * touchdowns
        + 2.0 * safeties
        + 2.0 * blocked_kicks
        + pa
    )


def _history_index(history_payload: Mapping[str, Any]) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, int, int], dict[str, float]]]:
    by_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
    team_week_rows: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for player in history_payload.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        team = _team(player.get("team"))
        name = normalize_name(str(player.get("player_display_name") or ""))
        games = [dict(row) for row in player.get("games") or [] if isinstance(row, Mapping)]
        if team and name and games:
            by_name[(team, name)] = games
        for row in games:
            season = int(float(row.get("season", 0) or 0))
            week = int(float(row.get("week", 0) or 0))
            if team and season and week:
                team_week_rows[(team, season, week)].append(row)

    team_games: dict[tuple[str, int, int], dict[str, float]] = {}
    for key, rows in team_week_rows.items():
        team_games[key] = {
            "pass_attempts": sum(float(r.get("attempts", 0.0) or 0.0) for r in rows),
            "rush_attempts": sum(float(r.get("carries", 0.0) or 0.0) for r in rows),
            "targets": sum(float(r.get("targets", 0.0) or 0.0) for r in rows),
            "pass_tds": sum(float(r.get("passing_tds", 0.0) or 0.0) for r in rows),
            "rush_tds": sum(float(r.get("rushing_tds", 0.0) or 0.0) for r in rows),
        }
    return by_name, team_games


def _team_environment(team: str, team_games: Mapping[tuple[str, int, int], Mapping[str, float]]) -> TeamEnvironment:
    rows = [
        (season, week, values)
        for (row_team, season, week), values in team_games.items()
        if _team(row_team) == team
    ]
    rows.sort(key=lambda x: (x[0], x[1]))
    rows = rows[-10:]
    pass_mean = _weighted([float(v["pass_attempts"]) for _, _, v in rows], default=34.0)
    rush_mean = _weighted([float(v["rush_attempts"]) for _, _, v in rows], default=27.0)
    pass_td = _weighted([float(v["pass_tds"]) for _, _, v in rows], default=1.55)
    rush_td = _weighted([float(v["rush_tds"]) for _, _, v in rows], default=1.05)
    return TeamEnvironment(
        team=team,
        pass_attempt_mean=_clamp(pass_mean, 20.0, 50.0),
        rush_attempt_mean=_clamp(rush_mean, 15.0, 45.0),
        pass_td_mean=_clamp(pass_td, 0.35, 4.0),
        rush_td_mean=_clamp(rush_td, 0.25, 3.5),
        field_goal_mean=1.65,
        history_games=len(rows),
    )


def _role_prior(position: str) -> dict[str, float]:
    pos = position.upper()
    if pos == "QB":
        return {"pass_share": 0.97, "carry_share": 0.13, "target_share": 0.0,
                "catch": 0.0, "ypt": 0.0, "ypc": 4.5, "pass_td_rate": .047,
                "rush_td_rate": .030, "rec_td_rate": 0.0, "int_rate": .022}
    if pos == "RB":
        return {"pass_share": 0.0, "carry_share": 0.38, "target_share": 0.12,
                "catch": .74, "ypt": 6.4, "ypc": 4.25, "pass_td_rate": 0.0,
                "rush_td_rate": .035, "rec_td_rate": .025, "int_rate": 0.0}
    if pos == "TE":
        return {"pass_share": 0.0, "carry_share": 0.005, "target_share": 0.14,
                "catch": .68, "ypt": 7.6, "ypc": 4.0, "pass_td_rate": 0.0,
                "rush_td_rate": .01, "rec_td_rate": .050, "int_rate": 0.0}
    return {"pass_share": 0.0, "carry_share": 0.02, "target_share": 0.20,
            "catch": .64, "ypt": 8.5, "ypc": 6.0, "pass_td_rate": 0.0,
            "rush_td_rate": .018, "rec_td_rate": .048, "int_rate": 0.0}


def _role_for_player(
    player: DKPlayer,
    *,
    history_rows: list[dict[str, Any]],
    team_env: TeamEnvironment,
    team_games: Mapping[tuple[str, int, int], Mapping[str, float]],
) -> PlayerRole:
    pos = "DST" if player.is_defense else (player.positions[0] if player.positions else "")
    prior = _role_prior(pos)
    if player.is_defense:
        return PlayerRole(player.player_id, player.name, player.team, "DST", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False, 0)

    cold = not history_rows
    row_shares: dict[str, list[float]] = {"pass": [], "carry": [], "target": []}
    for row in history_rows:
        key = (_team(row.get("team")), int(row.get("season", 0)), int(row.get("week", 0)))
        totals = team_games.get(key) or {}
        if float(totals.get("pass_attempts", 0.0)) > 0:
            row_shares["pass"].append(float(row.get("attempts", 0.0) or 0.0) / float(totals["pass_attempts"]))
        if float(totals.get("rush_attempts", 0.0)) > 0:
            row_shares["carry"].append(float(row.get("carries", 0.0) or 0.0) / float(totals["rush_attempts"]))
        if float(totals.get("targets", 0.0)) > 0:
            row_shares["target"].append(float(row.get("targets", 0.0) or 0.0) / float(totals["targets"]))

    pass_share = _clamp(_weighted(row_shares["pass"], default=prior["pass_share"]), 0.0, 1.0)
    carry_share = _clamp(_weighted(row_shares["carry"], default=prior["carry_share"]), 0.0, 1.0)
    target_share = _clamp(_weighted(row_shares["target"], default=prior["target_share"]), 0.0, 1.0)

    volume = NFLVolumeStage1()
    def volume_mean(metric: str, raw_field: str, team_mean: float, share: float) -> float:
        if not history_rows:
            return max(0.0, team_mean * share)
        history = [{metric: float(row.get(raw_field, 0.0) or 0.0)} for row in history_rows]
        try:
            return volume.project(
                player_id=player.player_id, metric=metric, history=history,
                team_opportunity_mean=max(team_mean, 1e-6), role_share=share,
            ).mean
        except Exception:
            return max(0.0, team_mean * share)

    catch_baseline = _ratio(history_rows, "receptions", "targets", prior["catch"], 12.0)
    ypt_baseline = _ratio(history_rows, "receiving_yards", "targets", prior["ypt"], 12.0)
    ypc_baseline = _ratio(history_rows, "rushing_yards", "carries", prior["ypc"], 15.0)
    catch = build_efficiency_distribution("catch_rate", {"baseline": catch_baseline, "uncertainty": .06}).mean
    ypt = build_efficiency_distribution("yards_per_target", {"baseline": ypt_baseline, "uncertainty": 1.6}).mean
    ypc = build_efficiency_distribution("yards_per_carry", {"baseline": ypc_baseline, "uncertainty": 1.1}).mean

    return PlayerRole(
        dk_player_id=player.player_id,
        name=player.name,
        team=_team(player.team),
        position=pos,
        pass_attempt_mean=volume_mean("pass_attempts", "attempts", team_env.pass_attempt_mean, pass_share),
        carry_mean=volume_mean("rush_attempts", "carries", team_env.rush_attempt_mean, carry_share),
        target_mean=volume_mean("targets", "targets", team_env.pass_attempt_mean, target_share),
        catch_rate=_clamp(catch, .25, .95),
        yards_per_target=_clamp(ypt, 3.0, 14.0),
        yards_per_carry=_clamp(ypc, 1.5, 9.0),
        pass_td_rate=_clamp(_ratio(history_rows, "passing_tds", "attempts", prior["pass_td_rate"], 45.0), .005, .12),
        rush_td_rate=_clamp(_ratio(history_rows, "rushing_tds", "carries", prior["rush_td_rate"], 35.0), .002, .20),
        rec_td_rate=_clamp(_ratio(history_rows, "receiving_tds", "targets", prior["rec_td_rate"], 30.0), .002, .20),
        int_rate=_clamp(_ratio(history_rows, "interceptions", "attempts", prior["int_rate"], 50.0), .002, .08),
        fumble_lost_per_game=_clamp(_weighted([float(r.get("fumbles_lost", 0.0) or 0.0) for r in history_rows], default=.025), 0.0, .5),
        cold_start=cold,
        history_games=len(history_rows),
    )


def build_nfl_joint_path_snapshot(
    *,
    players: Iterable[DKPlayer],
    history_payload: Mapping[str, Any],
    as_of: datetime,
    paths: int = 5000,
    seed: int = 20260914,
) -> dict[str, Any]:
    """Build correlated, market-blind NFL DraftKings player outcome paths.

    Correlation is created at the football-event level: opponents share a pace
    shock; team pass/rush volume is common; targets/carries are allocated within
    team; passing and receiving TD counts are identical by construction. The
    model is explicitly research-only until chronological DFS validation passes.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("NFL_DFS_AS_OF_TIMEZONE_REQUIRED")
    if paths < 1000:
        raise ValueError("NFL_DFS_PATH_COUNT_TOO_LOW")
    active = [p for p in players if not p.is_disabled]
    if not active:
        raise ValueError("NFL_DFS_ACTIVE_POOL_EMPTY")
    by_name, team_games = _history_index(history_payload)
    teams = sorted({_team(p.team) for p in active if p.team})
    env = {team: _team_environment(team, team_games) for team in teams}
    roles: dict[str, PlayerRole] = {}
    for player in active:
        rows = by_name.get((_team(player.team), normalize_name(player.name)), [])
        roles[player.player_id] = _role_for_player(
            player, history_rows=rows, team_env=env[_team(player.team)], team_games=team_games
        )

    samples: dict[str, list[dict[str, float]]] = {p.player_id: [] for p in active}
    by_team: dict[str, list[DKPlayer]] = defaultdict(list)
    for player in active:
        by_team[_team(player.team)].append(player)
    rng = random.Random(int(seed))

    games: set[tuple[str, str]] = set()
    for player in active:
        team, opp = _team(player.team), _team(player.opponent)
        if team and opp:
            games.add(tuple(sorted((team, opp))))
    if not games:
        raise ValueError("NFL_DFS_GAME_IDENTITY_MISSING")

    for _ in range(int(paths)):
        path_team_state: dict[str, dict[str, Any]] = {}
        for team_a, team_b in sorted(games):
            pace_sigma = .075
            pace = exp(rng.gauss(-.5 * pace_sigma * pace_sigma, pace_sigma))
            for team in (team_a, team_b):
                tenv = env.get(team) or TeamEnvironment(team, 34.0, 27.0, 1.55, 1.05, 1.65, 0)
                team_players = by_team.get(team, [])
                qbs = [p for p in team_players if "QB" in p.positions]
                rushers = [p for p in team_players if not p.is_defense and bool(set(p.positions) & {"QB", "RB", "WR", "TE"})]
                catchers = [p for p in team_players if not p.is_defense and bool(set(p.positions) & {"RB", "WR", "TE"})]
                pass_attempts = max(8, _poisson(rng, tenv.pass_attempt_mean * pace))
                rush_attempts = max(6, _poisson(rng, tenv.rush_attempt_mean * pace))
                pass_tds = _poisson(rng, tenv.pass_td_mean * pace)
                rush_tds = _poisson(rng, tenv.rush_td_mean * pace)
                field_goals = _poisson(rng, tenv.field_goal_mean)

                qb_counts = _allocate(rng, pass_attempts, qbs, [roles[p.player_id].pass_attempt_mean for p in qbs])
                carry_counts = _allocate(rng, rush_attempts, rushers, [roles[p.player_id].carry_mean for p in rushers])
                target_counts = _allocate(rng, pass_attempts, catchers, [roles[p.player_id].target_mean for p in catchers])
                qb_td_counts = _allocate(rng, pass_tds, qbs, [max(1e-5, qb_counts.get(p.player_id, 0)) for p in qbs])
                rec_td_counts = _allocate(
                    rng, pass_tds, catchers,
                    [max(1e-5, target_counts.get(p.player_id, 0) * roles[p.player_id].rec_td_rate) for p in catchers],
                )
                rush_td_counts = _allocate(
                    rng, rush_tds, rushers,
                    [max(1e-5, carry_counts.get(p.player_id, 0) * roles[p.player_id].rush_td_rate) for p in rushers],
                )

                team_rec_yards = 0.0
                player_rows: dict[str, dict[str, float]] = {}
                for player in team_players:
                    role = roles[player.player_id]
                    if player.is_defense:
                        continue
                    carries = carry_counts.get(player.player_id, 0)
                    targets = target_counts.get(player.player_id, 0)
                    receptions = _binomial(rng, targets, role.catch_rate) if targets else 0
                    rush_yards = max(0.0, rng.gauss(carries * role.yards_per_carry, sqrt(max(carries, 1)) * 2.0)) if carries else 0.0
                    rec_yards = max(0.0, rng.gauss(targets * role.yards_per_target, sqrt(max(targets, 1)) * 3.0)) if targets else 0.0
                    team_rec_yards += rec_yards
                    lost = 1.0 if rng.random() < min(.65, role.fumble_lost_per_game) else 0.0
                    row = {
                        "receptions": float(receptions),
                        "rec_yards": rec_yards,
                        "rec_tds": float(rec_td_counts.get(player.player_id, 0)),
                        "rush_yards": rush_yards,
                        "rush_tds": float(rush_td_counts.get(player.player_id, 0)),
                        "fumbles_lost": lost,
                    }
                    if "QB" in player.positions:
                        attempts = qb_counts.get(player.player_id, 0)
                        row.update({
                            "pass_yards": 0.0,
                            "pass_tds": float(qb_td_counts.get(player.player_id, 0)),
                            "interceptions": float(_binomial(rng, attempts, role.int_rate)),
                        })
                    player_rows[player.player_id] = row

                total_qb_attempts = sum(qb_counts.values())
                for qb in qbs:
                    if qb.player_id not in player_rows:
                        continue
                    share = qb_counts.get(qb.player_id, 0) / max(total_qb_attempts, 1)
                    player_rows[qb.player_id]["pass_yards"] = team_rec_yards * share

                offense_points = 7 * (pass_tds + rush_tds) + 3 * field_goals
                interceptions_thrown = sum(int(player_rows[p.player_id].get("interceptions", 0)) for p in qbs if p.player_id in player_rows)
                fumbles_lost = sum(int(row.get("fumbles_lost", 0)) for row in player_rows.values())
                path_team_state[team] = {
                    "player_rows": player_rows,
                    "offense_points": offense_points,
                    "interceptions_thrown": interceptions_thrown,
                    "fumbles_lost": fumbles_lost,
                }

            for team, opponent in ((team_a, team_b), (team_b, team_a)):
                state = path_team_state[team]
                opp_state = path_team_state[opponent]
                for pid, row in state["player_rows"].items():
                    samples[pid].append(row)
                defenses = [p for p in by_team.get(team, []) if p.is_defense]
                for defense in defenses:
                    sacks = _poisson(rng, 2.5)
                    turnovers = int(opp_state["interceptions_thrown"]) + int(opp_state["fumbles_lost"])
                    defensive_td = 1 if turnovers and rng.random() < min(.28, .065 * turnovers) else 0
                    safety = 1 if rng.random() < .025 else 0
                    blocked = 1 if rng.random() < .035 else 0
                    dk = _dst_points(
                        sacks=sacks,
                        interceptions=int(opp_state["interceptions_thrown"]),
                        fumble_recoveries=int(opp_state["fumbles_lost"]),
                        touchdowns=defensive_td,
                        safeties=safety,
                        blocked_kicks=blocked,
                        points_allowed=int(opp_state["offense_points"]),
                    )
                    samples[defense.player_id].append({"dk_points": float(dk)})

    if any(len(rows) != paths for rows in samples.values()):
        bad = {pid: len(rows) for pid, rows in samples.items() if len(rows) != paths}
        raise ValueError("NFL_DFS_PATH_ALIGNMENT_FAILED:" + json.dumps(bad, sort_keys=True))

    cold = [role for role in roles.values() if role.cold_start]
    identity = {
        "model_id": MODEL_ID,
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "paths": int(paths),
        "seed": int(seed),
        "history_current_sha": history_payload.get("current_source_sha256"),
        "history_prior_sha": history_payload.get("prior_source_sha256"),
        "players": sorted((p.player_id, p.name, p.team) for p in active),
    }
    path_set_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1,
        "sport": "NFL",
        "model_id": MODEL_ID,
        "status": STATUS,
        "updated_at": as_of.astimezone(timezone.utc).isoformat(),
        "source": "SPORTSEDGE_NFL_PIT_VOLUME_EFFICIENCY_JOINT_SIM",
        "path_set_id": path_set_id,
        "path_count": int(paths),
        "seed": int(seed),
        "history_source": {
            "current_uri": history_payload.get("current_source_uri"),
            "current_sha256": history_payload.get("current_source_sha256"),
            "prior_uri": history_payload.get("prior_source_uri"),
            "prior_sha256": history_payload.get("prior_source_sha256"),
            "strictly_prior_week_only": history_payload.get("strictly_prior_week_only"),
        },
        "diagnostics": {
            "active_player_count": len(active),
            "cold_start_player_count": len(cold),
            "cold_start_rate": len(cold) / max(1, len(active)),
            "team_history_games": {team: tenv.history_games for team, tenv in env.items()},
            "validation_status": "UNVALIDATED_RESEARCH_ONLY",
        },
        "players": [
            {
                "player_id": player.player_id,
                "name": player.name,
                "team": player.team,
                "source": "SPORTSEDGE_NFL_JOINT_PATHS",
                "updated_at": as_of.astimezone(timezone.utc).isoformat(),
                "path_set_id": path_set_id,
                "samples": samples[player.player_id],
            }
            for player in active
        ],
    }
