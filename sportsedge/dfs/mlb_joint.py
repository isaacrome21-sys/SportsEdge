from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import exp, sqrt
import random
from typing import Any, Iterable, Mapping

from sportsedge.sports.mlb.prop_efficiency_engine import build_efficiency_distribution
from sportsedge.sports.mlb.prop_volume_stage1 import MLBVolumeStage1

from .sources.common import normalize_team
from .types import DKPlayer

MODEL_ID = "MLB_DFS_JOINT_PATHS_V1_RESEARCH"
STATUS = "RESEARCH_ONLY_UNVALIDATED_DFS_DISTRIBUTION"

_BATTING_ORDER_PA = {1: 4.65, 2: 4.55, 3: 4.45, 4: 4.35, 5: 4.25, 6: 4.15, 7: 4.05, 8: 3.95, 9: 3.85}


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, float(value)))


def _ratio(num: float, den: float, prior: float, prior_n: float) -> float:
    return (max(0.0, num) + prior * prior_n) / max(max(0.0, den) + prior_n, 1e-9)


def _poisson(rng: random.Random, mean: float) -> int:
    lam = max(0.0, float(mean))
    if lam <= 0:
        return 0
    if lam >= 18:
        return max(0, int(round(rng.gauss(lam, sqrt(lam)))))
    threshold = exp(-lam)
    product = 1.0
    k = 0
    while product > threshold:
        k += 1
        product *= rng.random()
    return k - 1


def _binomial(rng: random.Random, n: int, p: float) -> int:
    n = max(0, int(n))
    p = _clamp(p, 0.0, 1.0)
    if n == 0 or p == 0:
        return 0
    if p == 1:
        return n
    if n >= 25:
        mean = n * p
        sd = sqrt(max(n * p * (1.0 - p), 1e-9))
        return min(n, max(0, int(round(rng.gauss(mean, sd)))))
    return sum(1 for _ in range(n) if rng.random() < p)


def _allocate(rng: random.Random, total: int, ids: list[str], weights: list[float]) -> dict[str, int]:
    if not ids:
        return {}
    out = {pid: 0 for pid in ids}
    positive = [max(1e-9, float(w)) for w in weights]
    if total <= 0:
        return out
    for pid in rng.choices(ids, weights=positive, k=int(total)):
        out[pid] += 1
    return out


def _stats_index(stats_snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in stats_snapshot.get("players") or []:
        if isinstance(row, Mapping):
            pid = str(row.get("dk_player_id") or "")
            if pid:
                out[pid] = row
    return out


def _rate_mean(metric: str, baseline: float, uncertainty: float = .06) -> float:
    return build_efficiency_distribution(metric, {"baseline": _clamp(baseline, .001, .999), "uncertainty": uncertainty}).mean


def _hitter_profile(player: DKPlayer, row: Mapping[str, Any]) -> dict[str, float]:
    stat = row.get("hitting") if isinstance(row.get("hitting"), Mapping) else {}
    pa = float(stat.get("plate_appearances", 0.0) or 0.0)
    games = float(stat.get("games", 0.0) or 0.0)
    order = int(player.raw.get("mlb_batting_order") or 0)
    if order not in _BATTING_ORDER_PA:
        raise ValueError(f"MLB_DFS_BATTING_ORDER_MISSING:{player.team}:{player.name}")
    role_pa = _BATTING_ORDER_PA[order]
    per_game = pa / games if games > 0 else role_pa
    try:
        opportunity = MLBVolumeStage1().project(
            player_id=player.player_id,
            metric="plate_appearances",
            history=[{"plate_appearances": per_game}],
            role_opportunity_mean=role_pa,
        ).mean
    except Exception:
        opportunity = role_pa
    singles = float(stat.get("singles", 0.0) or 0.0)
    doubles = float(stat.get("doubles", 0.0) or 0.0)
    triples = float(stat.get("triples", 0.0) or 0.0)
    homers = float(stat.get("home_runs", 0.0) or 0.0)
    walks = float(stat.get("walks", 0.0) or 0.0)
    hbp = float(stat.get("hbp", 0.0) or 0.0)
    strikeouts = float(stat.get("strikeouts", 0.0) or 0.0)
    hit_rate = _rate_mean("hit_rate", _ratio(singles + doubles + triples + homers, pa, .225, 100.0))
    xb_rate = _rate_mean("extra_base_hit_rate", _ratio(doubles + triples + homers, pa, .080, 120.0))
    k_rate = _rate_mean("strikeout_rate", _ratio(strikeouts, pa, .225, 110.0))
    bb_rate = _rate_mean("walk_rate", _ratio(walks, pa, .082, 110.0))
    hr_rate = _ratio(homers, pa, .032, 140.0)
    triple_rate = _ratio(triples, pa, .004, 180.0)
    double_rate = max(0.0, xb_rate - hr_rate - triple_rate)
    single_rate = max(.001, hit_rate - double_rate - triple_rate - hr_rate)
    hbp_rate = _ratio(hbp, pa, .011, 140.0)
    on_base = max(1.0, singles + doubles + triples + homers + walks + hbp)
    sb_rate = _ratio(float(stat.get("stolen_bases", 0.0) or 0.0), on_base, .055, 35.0)
    # Rebalance only if empirical/shrunken categories would exceed one PA.
    categories = single_rate + double_rate + triple_rate + hr_rate + bb_rate + hbp_rate + k_rate
    if categories > .94:
        scale = .94 / categories
        single_rate *= scale
        double_rate *= scale
        triple_rate *= scale
        hr_rate *= scale
        bb_rate *= scale
        hbp_rate *= scale
        k_rate *= scale
    return {
        "pa_mean": opportunity,
        "single_rate": single_rate,
        "double_rate": double_rate,
        "triple_rate": triple_rate,
        "hr_rate": hr_rate,
        "walk_rate": bb_rate,
        "hbp_rate": hbp_rate,
        "k_rate": k_rate,
        "sb_rate": _clamp(sb_rate, 0.0, .45),
        "order": float(order),
    }


def _pitcher_profile(player: DKPlayer, row: Mapping[str, Any]) -> dict[str, float]:
    stat = row.get("pitching") if isinstance(row.get("pitching"), Mapping) else {}
    starts = float(stat.get("games_started", 0.0) or 0.0)
    bf = float(stat.get("batters_faced", 0.0) or 0.0)
    pitches = float(stat.get("pitches_thrown", 0.0) or 0.0)
    bf_per_start = bf / starts if starts > 0 else 22.0
    pitch_per_start = pitches / starts if starts > 0 else 92.0
    volume = MLBVolumeStage1()
    try:
        bf_mean = volume.project(
            player_id=player.player_id, metric="batters_faced",
            history=[{"batters_faced": bf_per_start}], role_opportunity_mean=bf_per_start,
        ).mean
    except Exception:
        bf_mean = bf_per_start
    try:
        pitch_mean = volume.project(
            player_id=player.player_id, metric="pitches_thrown",
            history=[{"pitches_thrown": pitch_per_start}], role_opportunity_mean=pitch_per_start,
        ).mean
    except Exception:
        pitch_mean = pitch_per_start
    k_rate = _rate_mean("strikeout_rate", _ratio(float(stat.get("strikeouts", 0.0) or 0.0), bf, .225, 120.0))
    bb_rate = _rate_mean("walk_rate", _ratio(float(stat.get("walks_allowed", 0.0) or 0.0), bf, .082, 120.0))
    hit_rate = _rate_mean("hit_rate", _ratio(float(stat.get("hits_allowed", 0.0) or 0.0), bf, .225, 120.0))
    er_rate = _ratio(float(stat.get("earned_runs", 0.0) or 0.0), bf, .115, 150.0)
    hbp_rate = _ratio(float(stat.get("hbp_allowed", 0.0) or 0.0), bf, .011, 160.0)
    return {
        "bf_mean": _clamp(bf_mean, 8.0, 35.0),
        "pitch_mean": _clamp(pitch_mean, 35.0, 125.0),
        "k_rate": k_rate,
        "bb_rate": bb_rate,
        "hit_rate": hit_rate,
        "er_rate": _clamp(er_rate, .02, .30),
        "hbp_rate": _clamp(hbp_rate, .001, .06),
    }


def build_mlb_joint_path_snapshot(
    *,
    players: Iterable[DKPlayer],
    stats_snapshot: Mapping[str, Any],
    as_of: datetime,
    paths: int = 5000,
    seed: int = 20260914,
) -> dict[str, Any]:
    """Build correlated MLB hitter/pitcher DraftKings paths from confirmed lineups.

    Every team must have exactly nine reconciled confirmed hitters and one reconciled
    probable starter. Opponent hitter outcomes are used to construct starter hits,
    walks, strikeouts and earned runs, and simulated run differential controls the
    starter win bonus. This keeps stacks and opposing pitchers mechanically linked.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("MLB_DFS_AS_OF_TIMEZONE_REQUIRED")
    if paths < 1000:
        raise ValueError("MLB_DFS_PATH_COUNT_TOO_LOW")
    active = [p for p in players if not p.is_disabled]
    if not active:
        raise ValueError("MLB_DFS_ACTIVE_POOL_EMPTY")
    stats = _stats_index(stats_snapshot)
    missing_stats = [p.player_id for p in active if p.player_id not in stats]
    if len(missing_stats) / max(1, len(active)) > .10:
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
        opp = next(iter(opponents))
        games.add(tuple(sorted((team, opp))))
    for a, b in games:
        if a not in hitters_by_team or b not in hitters_by_team:
            raise ValueError(f"MLB_DFS_GAME_POOL_INCOMPLETE:{a}:{b}")

    hitter_profiles = {
        p.player_id: _hitter_profile(p, stats[p.player_id])
        for team in hitters_by_team.values() for p in team
        if p.player_id in stats
    }
    pitcher_profiles = {
        p.player_id: _pitcher_profile(p, stats[p.player_id])
        for p in pitcher_by_team.values() if p.player_id in stats
    }
    if len(hitter_profiles) != sum(len(x) for x in hitters_by_team.values()) or len(pitcher_profiles) != len(pitcher_by_team):
        raise ValueError("MLB_DFS_PROFILE_BIND_INCOMPLETE")

    samples: dict[str, list[dict[str, float]]] = {p.player_id: [] for p in active}
    rng = random.Random(int(seed))
    for _ in range(int(paths)):
        for team_a, team_b in sorted(games):
            game_results: dict[str, dict[str, Any]] = {}
            for team, opp in ((team_a, team_b), (team_b, team_a)):
                lineup = hitters_by_team[team]
                opposing_pitcher = pitcher_by_team[opp]
                pprof = pitcher_profiles[opposing_pitcher.player_id]
                offense_sigma = .12
                offense_shock = exp(rng.gauss(-.5 * offense_sigma * offense_sigma, offense_sigma))
                # Pitcher-quality modifier centers at league-average hit/K rates.
                contact_modifier = _clamp((pprof["hit_rate"] / .225) ** -.45, .75, 1.25)
                k_modifier = _clamp(pprof["k_rate"] / .225, .70, 1.40)
                hitter_rows: dict[str, dict[str, float]] = {}
                aggregate = {"hits": 0, "walks": 0, "hbp": 0, "strikeouts": 0, "total_bases": 0, "on_base": 0}
                for hitter in lineup:
                    profile = hitter_profiles[hitter.player_id]
                    pa_mean = profile["pa_mean"] * (offense_shock ** .30)
                    pa = max(2, min(7, _poisson(rng, pa_mean)))
                    row = {"singles": 0, "doubles": 0, "triples": 0, "home_runs": 0,
                           "rbi": 0, "runs": 0, "walks": 0, "hbp": 0, "stolen_bases": 0,
                           "strikeouts": 0, "plate_appearances": float(pa)}
                    for _pa in range(pa):
                        single = profile["single_rate"] * offense_shock * contact_modifier
                        double = profile["double_rate"] * offense_shock * contact_modifier
                        triple = profile["triple_rate"] * offense_shock * contact_modifier
                        homer = profile["hr_rate"] * (offense_shock ** 1.25) * contact_modifier
                        walk = .55 * profile["walk_rate"] + .45 * pprof["bb_rate"]
                        hbp = .55 * profile["hbp_rate"] + .45 * pprof["hbp_rate"]
                        strikeout = _clamp(profile["k_rate"] * k_modifier, .05, .45)
                        total = single + double + triple + homer + walk + hbp + strikeout
                        if total > .95:
                            scale = .95 / total
                            single *= scale; double *= scale; triple *= scale; homer *= scale
                            walk *= scale; hbp *= scale; strikeout *= scale
                        u = rng.random()
                        thresholds = (
                            ("home_runs", homer), ("triples", triple), ("doubles", double),
                            ("singles", single), ("walks", walk), ("hbp", hbp), ("strikeouts", strikeout),
                        )
                        acc = 0.0
                        for event, prob in thresholds:
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

                run_mean = max(.08, .10 * aggregate["on_base"] + .28 * aggregate["total_bases"])
                team_runs = _poisson(rng, run_mean)
                run_ids = [p.player_id for p in lineup]
                run_weights = [
                    1.0 + hitter_rows[p.player_id]["singles"] + hitter_rows[p.player_id]["doubles"]
                    + hitter_rows[p.player_id]["triples"] + 1.5 * hitter_rows[p.player_id]["home_runs"]
                    + hitter_rows[p.player_id]["walks"] + hitter_rows[p.player_id]["hbp"]
                    for p in lineup
                ]
                run_alloc = _allocate(rng, team_runs, run_ids, run_weights)
                rbi_total = _binomial(rng, team_runs, .92)
                rbi_weights = [
                    .5 + hitter_rows[p.player_id]["singles"] + 1.5 * hitter_rows[p.player_id]["doubles"]
                    + 2.0 * hitter_rows[p.player_id]["triples"] + 3.0 * hitter_rows[p.player_id]["home_runs"]
                    for p in lineup
                ]
                rbi_alloc = _allocate(rng, rbi_total, run_ids, rbi_weights)
                for pid, row in hitter_rows.items():
                    row["runs"] = run_alloc.get(pid, 0)
                    row["rbi"] = rbi_alloc.get(pid, 0)
                    samples[pid].append({key: float(value) for key, value in row.items() if key != "strikeouts" and key != "plate_appearances"})
                game_results[team] = {"runs": team_runs, "aggregate": aggregate, "hitter_rows": hitter_rows}

            for team, opp in ((team_a, team_b), (team_b, team_a)):
                pitcher = pitcher_by_team[team]
                pprof = pitcher_profiles[pitcher.player_id]
                opp_result = game_results[opp]
                aggregate = opp_result["aggregate"]
                opp_pa = sum(int(row["plate_appearances"]) for row in opp_result["hitter_rows"].values())
                bf = max(8, min(35, _poisson(rng, pprof["bf_mean"])))
                starter_fraction = _clamp(bf / max(opp_pa, 1), .20, .92)
                hits_allowed = _binomial(rng, aggregate["hits"], starter_fraction)
                walks_allowed = _binomial(rng, aggregate["walks"], starter_fraction)
                hbp_allowed = _binomial(rng, aggregate["hbp"], starter_fraction)
                strikeouts = _binomial(rng, aggregate["strikeouts"], starter_fraction)
                earned_runs = _binomial(rng, int(opp_result["runs"]), starter_fraction)
                outs = max(0, min(27, bf - hits_allowed - walks_allowed - hbp_allowed))
                own_runs = int(game_results[team]["runs"])
                opp_runs = int(opp_result["runs"])
                win = 1.0 if outs >= 15 and own_runs > opp_runs else 0.0
                samples[pitcher.player_id].append({
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
                })

    if any(len(rows) != paths for rows in samples.values()):
        bad = {pid: len(rows) for pid, rows in samples.items() if len(rows) != paths}
        raise ValueError("MLB_DFS_PATH_ALIGNMENT_FAILED:" + json.dumps(bad, sort_keys=True))
    identity = {
        "model_id": MODEL_ID,
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "paths": int(paths), "seed": int(seed),
        "stats_manifest": stats_snapshot.get("source_manifest_sha256"),
        "players": sorted((p.player_id, p.name, p.team, p.raw.get("mlb_batting_order")) for p in active),
    }
    path_set_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1,
        "sport": "MLB",
        "model_id": MODEL_ID,
        "status": STATUS,
        "updated_at": as_of.astimezone(timezone.utc).isoformat(),
        "source": "SPORTSEDGE_MLB_STATSAPI_PIT_JOINT_SIM",
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
            "validation_status": "UNVALIDATED_RESEARCH_ONLY",
        },
        "players": [
            {"player_id": p.player_id, "name": p.name, "team": p.team,
             "source": "SPORTSEDGE_MLB_JOINT_PATHS",
             "updated_at": as_of.astimezone(timezone.utc).isoformat(),
             "path_set_id": path_set_id, "samples": samples[p.player_id]}
            for p in active
        ],
    }
