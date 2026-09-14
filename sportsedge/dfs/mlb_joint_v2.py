from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import exp
import random
from typing import Any, Iterable, Mapping

from .mlb_joint import (
    _allocate,
    _binomial,
    _clamp,
    _hitter_profile,
    _pitcher_profile,
    _poisson,
    _stats_index,
)
from .sources.common import normalize_team
from .types import DKPlayer

MODEL_ID = "MLB_DFS_JOINT_PATHS_V2_STARTER_STINT_RESEARCH"
STATUS = "RESEARCH_ONLY_UNVALIDATED_DFS_DISTRIBUTION"


def _allocate_inning_runs(rng: random.Random, runs: int) -> list[int]:
    """Allocate simulated runs over regulation innings.

    This is an explicit research approximation used only to determine which runs
    occurred before/after a starter's hook and whether the bullpen preserved his
    lead. It is not a play-by-play simulator.
    """
    innings = [0] * 9
    if runs <= 0:
        return innings
    # Slightly downweight the ninth because home teams leading after 8.5 innings
    # do not bat in the bottom of the ninth. Home/away half-inning state is not yet
    # modeled, so keep the adjustment small and record the approximation upstream.
    weights = [1.0, 1.0, 1.0, 1.02, 1.02, 1.03, 1.04, 1.04, 0.92]
    for inning in rng.choices(range(9), weights=weights, k=int(runs)):
        innings[inning] += 1
    return innings


def _split_runs_at_exit(
    rng: random.Random,
    inning_runs: list[int],
    outs: int,
) -> tuple[int, list[int]]:
    """Split team runs into pre-exit and post-exit portions.

    Completed innings are wholly pre-exit. For a partial inning, runs are split
    with a simple outs/3 exposure fraction. The remaining runs are retained by
    inning so bullpen lead preservation can be evaluated path-by-path.
    """
    outs = max(0, min(27, int(outs)))
    completed = min(9, outs // 3)
    partial_outs = outs % 3
    pre = sum(inning_runs[:completed])
    post = [0] * 9
    for inning in range(completed + (1 if partial_outs else 0), 9):
        post[inning] = int(inning_runs[inning])
    if completed < 9 and partial_outs:
        current = int(inning_runs[completed])
        before = _binomial(rng, current, partial_outs / 3.0)
        pre += before
        post[completed] = current - before
    return pre, post


def _bullpen_preserved_lead(
    rng: random.Random,
    *,
    own_pre: int,
    opp_pre: int,
    own_post: list[int],
    opp_post: list[int],
) -> bool:
    """Return True only if the starter's lead is never tied or lost after exit."""
    own = int(own_pre)
    opp = int(opp_pre)
    if own <= opp:
        return False
    for inning in range(9):
        events = [1] * int(own_post[inning]) + [-1] * int(opp_post[inning])
        rng.shuffle(events)
        for event in events:
            if event > 0:
                own += 1
            else:
                opp += 1
            # Under MLB pitcher-win rules, once the lead is relinquished the
            # starter cannot regain the win even if his team later wins.
            if own <= opp:
                return False
    return own > opp


def _simulate_starter_stint(
    rng: random.Random,
    *,
    pitcher_profile: Mapping[str, float],
    opponent_result: Mapping[str, Any],
    own_result: Mapping[str, Any],
) -> dict[str, float]:
    aggregate = opponent_result["aggregate"]
    hitter_rows = opponent_result["hitter_rows"]
    opp_pa = sum(int(row["plate_appearances"]) for row in hitter_rows.values())

    mean_pitches = float(pitcher_profile["pitch_mean"])
    mean_bf = float(pitcher_profile["bf_mean"])
    pitch_sd = max(7.0, mean_pitches * 0.08)
    pitch_budget = int(round(rng.gauss(mean_pitches, pitch_sd)))
    pitch_budget = max(35, min(120, pitch_budget))
    pitches_per_bf = _clamp(mean_pitches / max(mean_bf, 1.0), 3.2, 5.3)
    bf_by_pitch = max(8, int(pitch_budget // pitches_per_bf))
    bf_draw = max(8, min(35, _poisson(rng, mean_bf)))
    batters_faced = max(8, min(35, bf_draw, bf_by_pitch, max(8, opp_pa)))
    starter_fraction = _clamp(batters_faced / max(opp_pa, 1), 0.12, 0.92)

    hits_allowed = _binomial(rng, int(aggregate["hits"]), starter_fraction)
    walks_allowed = _binomial(rng, int(aggregate["walks"]), starter_fraction)
    hbp_allowed = _binomial(rng, int(aggregate["hbp"]), starter_fraction)
    strikeouts = _binomial(rng, int(aggregate["strikeouts"]), starter_fraction)
    outs = max(0, min(27, batters_faced - hits_allowed - walks_allowed - hbp_allowed))

    opp_pre, opp_post = _split_runs_at_exit(rng, list(opponent_result["inning_runs"]), outs)
    own_pre, own_post = _split_runs_at_exit(rng, list(own_result["inning_runs"]), outs)
    qualified_five = outs >= 15
    lead_at_exit = qualified_five and own_pre > opp_pre
    bullpen_hold = False
    if lead_at_exit:
        bullpen_hold = _bullpen_preserved_lead(
            rng,
            own_pre=own_pre,
            opp_pre=opp_pre,
            own_post=own_post,
            opp_post=opp_post,
        )
    win = 1.0 if qualified_five and lead_at_exit and bullpen_hold else 0.0

    # Most runs are earned, but not all. Crucially, only runs occurring before the
    # simulated hook are eligible to be charged to the starter.
    earned_runs = _binomial(rng, int(opp_pre), 0.92)
    actual_pitches = min(pitch_budget, max(1, int(round(batters_faced * pitches_per_bf))))
    return {
        "outs": float(outs),
        "strikeouts": float(strikeouts),
        "earned_runs": float(earned_runs),
        "hits_allowed": float(hits_allowed),
        "walks_allowed": float(walks_allowed),
        "hbp_allowed": float(hbp_allowed),
        "win_probability": win,
        "complete_game_probability": 0.0,
        "cg_shutout_probability": 0.0,
        "no_hitter_probability": 0.0,
        "batters_faced": float(batters_faced),
        "pitches_thrown": float(actual_pitches),
        "lead_at_exit": 1.0 if lead_at_exit else 0.0,
        "bullpen_hold": 1.0 if bullpen_hold else 0.0,
        "opponent_runs_before_exit": float(opp_pre),
    }


def build_mlb_joint_path_snapshot_v2(
    *,
    players: Iterable[DKPlayer],
    stats_snapshot: Mapping[str, Any],
    as_of: datetime,
    paths: int = 5000,
    seed: int = 20260914,
) -> dict[str, Any]:
    """Correlated MLB DFS paths with explicit starter hook/win accounting."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("MLB_DFS_AS_OF_TIMEZONE_REQUIRED")
    if paths < 1000:
        raise ValueError("MLB_DFS_PATH_COUNT_TOO_LOW")
    active = [p for p in players if not p.is_disabled]
    if not active:
        raise ValueError("MLB_DFS_ACTIVE_POOL_EMPTY")
    stats = _stats_index(stats_snapshot)
    missing_stats = [p.player_id for p in active if p.player_id not in stats]
    if len(missing_stats) / max(1, len(active)) > 0.10:
        raise ValueError("MLB_DFS_STATS_COVERAGE_LOW:" + ",".join(sorted(missing_stats)[:12]))

    by_team: dict[str, list[DKPlayer]] = defaultdict(list)
    for player in active:
        by_team[normalize_team(player.team)].append(player)
    hitters_by_team: dict[str, list[DKPlayer]] = {}
    pitcher_by_team: dict[str, DKPlayer] = {}
    for team, roster in by_team.items():
        hitters = [p for p in roster if not p.is_pitcher]
        pitchers = [p for p in roster if p.is_pitcher]
        if len(hitters) != 9 or any(not p.raw.get("mlb_confirmed_lineup") for p in hitters):
            raise ValueError(f"MLB_DFS_LINEUP_UNCONFIRMED:{team}:{len(hitters)}")
        if len(pitchers) != 1 or not pitchers[0].raw.get("mlb_probable_starter"):
            raise ValueError(f"MLB_DFS_PROBABLE_STARTER_UNCONFIRMED:{team}:{len(pitchers)}")
        hitters.sort(key=lambda p: int(p.raw.get("mlb_batting_order") or 99))
        if [int(p.raw.get("mlb_batting_order") or 0) for p in hitters] != list(range(1, 10)):
            raise ValueError(f"MLB_DFS_BATTING_ORDER_INVALID:{team}")
        hitters_by_team[team] = hitters
        pitcher_by_team[team] = pitchers[0]

    games: set[tuple[str, str]] = set()
    for team, roster in by_team.items():
        opponents = {normalize_team(p.opponent) for p in roster if p.opponent}
        if len(opponents) != 1:
            raise ValueError(f"MLB_DFS_OPPONENT_AMBIGUOUS:{team}:{sorted(opponents)}")
        games.add(tuple(sorted((team, next(iter(opponents))))))
    for a, b in games:
        if a not in hitters_by_team or b not in hitters_by_team:
            raise ValueError(f"MLB_DFS_GAME_POOL_INCOMPLETE:{a}:{b}")

    hitter_profiles = {
        p.player_id: _hitter_profile(p, stats[p.player_id])
        for roster in hitters_by_team.values()
        for p in roster
        if p.player_id in stats
    }
    pitcher_profiles = {
        p.player_id: _pitcher_profile(p, stats[p.player_id])
        for p in pitcher_by_team.values()
        if p.player_id in stats
    }
    if len(hitter_profiles) != sum(len(x) for x in hitters_by_team.values()):
        raise ValueError("MLB_DFS_HITTER_PROFILE_BIND_INCOMPLETE")
    if len(pitcher_profiles) != len(pitcher_by_team):
        raise ValueError("MLB_DFS_PITCHER_PROFILE_BIND_INCOMPLETE")

    samples: dict[str, list[dict[str, float]]] = {p.player_id: [] for p in active}
    rng = random.Random(int(seed))
    for _ in range(int(paths)):
        for team_a, team_b in sorted(games):
            game_results: dict[str, dict[str, Any]] = {}
            for team, opp in ((team_a, team_b), (team_b, team_a)):
                lineup = hitters_by_team[team]
                opposing_pitcher = pitcher_by_team[opp]
                pprof = pitcher_profiles[opposing_pitcher.player_id]
                offense_sigma = 0.12
                offense_shock = exp(rng.gauss(-0.5 * offense_sigma * offense_sigma, offense_sigma))
                contact_modifier = _clamp((pprof["hit_rate"] / 0.225) ** -0.45, 0.75, 1.25)
                k_modifier = _clamp(pprof["k_rate"] / 0.225, 0.70, 1.40)
                hitter_rows: dict[str, dict[str, float]] = {}
                aggregate = {"hits": 0, "walks": 0, "hbp": 0, "strikeouts": 0, "total_bases": 0, "on_base": 0}
                for hitter in lineup:
                    profile = hitter_profiles[hitter.player_id]
                    pa = max(2, min(7, _poisson(rng, profile["pa_mean"] * (offense_shock ** 0.30))))
                    row = {
                        "singles": 0, "doubles": 0, "triples": 0, "home_runs": 0,
                        "rbi": 0, "runs": 0, "walks": 0, "hbp": 0, "stolen_bases": 0,
                        "strikeouts": 0, "plate_appearances": float(pa),
                    }
                    for _pa in range(pa):
                        rates = [
                            ("home_runs", profile["hr_rate"] * (offense_shock ** 1.25) * contact_modifier),
                            ("triples", profile["triple_rate"] * offense_shock * contact_modifier),
                            ("doubles", profile["double_rate"] * offense_shock * contact_modifier),
                            ("singles", profile["single_rate"] * offense_shock * contact_modifier),
                            ("walks", 0.55 * profile["walk_rate"] + 0.45 * pprof["bb_rate"]),
                            ("hbp", 0.55 * profile["hbp_rate"] + 0.45 * pprof["hbp_rate"]),
                            ("strikeouts", _clamp(profile["k_rate"] * k_modifier, 0.05, 0.45)),
                        ]
                        total = sum(prob for _, prob in rates)
                        if total > 0.95:
                            scale = 0.95 / total
                            rates = [(name, prob * scale) for name, prob in rates]
                        u = rng.random()
                        acc = 0.0
                        for event, prob in rates:
                            acc += prob
                            if u < acc:
                                row[event] += 1
                                break
                    hits = row["singles"] + row["doubles"] + row["triples"] + row["home_runs"]
                    on_base = hits + row["walks"] + row["hbp"]
                    total_bases = row["singles"] + 2 * row["doubles"] + 3 * row["triples"] + 4 * row["home_runs"]
                    row["stolen_bases"] = _binomial(rng, on_base, profile["sb_rate"])
                    aggregate["hits"] += hits
                    aggregate["walks"] += row["walks"]
                    aggregate["hbp"] += row["hbp"]
                    aggregate["strikeouts"] += row["strikeouts"]
                    aggregate["total_bases"] += total_bases
                    aggregate["on_base"] += on_base
                    hitter_rows[hitter.player_id] = row

                run_mean = max(0.08, 0.10 * aggregate["on_base"] + 0.28 * aggregate["total_bases"])
                team_runs = _poisson(rng, run_mean)
                run_ids = [p.player_id for p in lineup]
                run_weights = [
                    1.0 + hitter_rows[p.player_id]["singles"] + hitter_rows[p.player_id]["doubles"]
                    + hitter_rows[p.player_id]["triples"] + 1.5 * hitter_rows[p.player_id]["home_runs"]
                    + hitter_rows[p.player_id]["walks"] + hitter_rows[p.player_id]["hbp"]
                    for p in lineup
                ]
                run_alloc = _allocate(rng, team_runs, run_ids, run_weights)
                rbi_total = _binomial(rng, team_runs, 0.92)
                rbi_weights = [
                    0.5 + hitter_rows[p.player_id]["singles"] + 1.5 * hitter_rows[p.player_id]["doubles"]
                    + 2.0 * hitter_rows[p.player_id]["triples"] + 3.0 * hitter_rows[p.player_id]["home_runs"]
                    for p in lineup
                ]
                rbi_alloc = _allocate(rng, rbi_total, run_ids, rbi_weights)
                for pid, row in hitter_rows.items():
                    row["runs"] = run_alloc.get(pid, 0)
                    row["rbi"] = rbi_alloc.get(pid, 0)
                    samples[pid].append({
                        key: float(value)
                        for key, value in row.items()
                        if key not in {"strikeouts", "plate_appearances"}
                    })
                game_results[team] = {
                    "runs": team_runs,
                    "inning_runs": _allocate_inning_runs(rng, team_runs),
                    "aggregate": aggregate,
                    "hitter_rows": hitter_rows,
                }

            for team, opp in ((team_a, team_b), (team_b, team_a)):
                pitcher = pitcher_by_team[team]
                samples[pitcher.player_id].append(
                    _simulate_starter_stint(
                        rng,
                        pitcher_profile=pitcher_profiles[pitcher.player_id],
                        opponent_result=game_results[opp],
                        own_result=game_results[team],
                    )
                )

    if any(len(rows) != paths for rows in samples.values()):
        bad = {pid: len(rows) for pid, rows in samples.items() if len(rows) != paths}
        raise ValueError("MLB_DFS_PATH_ALIGNMENT_FAILED:" + json.dumps(bad, sort_keys=True))
    identity = {
        "model_id": MODEL_ID,
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "paths": int(paths),
        "seed": int(seed),
        "stats_manifest": stats_snapshot.get("source_manifest_sha256"),
        "players": sorted((p.player_id, p.name, p.team, p.raw.get("mlb_batting_order")) for p in active),
    }
    path_set_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 2,
        "sport": "MLB",
        "model_id": MODEL_ID,
        "status": STATUS,
        "updated_at": as_of.astimezone(timezone.utc).isoformat(),
        "source": "SPORTSEDGE_MLB_STATSAPI_PIT_JOINT_SIM_V2",
        "path_set_id": path_set_id,
        "path_count": int(paths),
        "seed": int(seed),
        "history_source": {
            "source": stats_snapshot.get("source"),
            "source_manifest_sha256": stats_snapshot.get("source_manifest_sha256"),
            "provenance_mode": stats_snapshot.get("provenance_mode"),
        },
        "diagnostics": {
            "active_player_count": len(active),
            "confirmed_team_count": len(hitters_by_team),
            "probable_pitcher_count": len(pitcher_by_team),
            "stats_coverage": stats_snapshot.get("coverage"),
            "starter_stint_model": "PITCH_BUDGET_BF_HOOK_PLUS_EXIT_LEAD_AND_BULLPEN_HOLD",
            "inning_allocation": "RESEARCH_APPROXIMATION",
            "validation_status": "UNVALIDATED_RESEARCH_ONLY",
        },
        "players": [
            {
                "player_id": p.player_id,
                "name": p.name,
                "team": p.team,
                "source": "SPORTSEDGE_MLB_JOINT_PATHS_V2",
                "updated_at": as_of.astimezone(timezone.utc).isoformat(),
                "path_set_id": path_set_id,
                "samples": samples[p.player_id],
            }
            for p in active
        ],
    }
