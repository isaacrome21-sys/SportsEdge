"""Conservation-checked joint HR x H+R+RBI readout from aligned MLB game paths.

Research-only foundation (t184 Lane 2). It reads the SAME simulated games the
endogenous joint simulator (sportsedge.dfs.mlb_joint_paths) produces and:

* refuses the path set unless run accounting is conserved on every path:
  sum of lineup runs == that team's game runs, sum of lineup RBI <= team runs,
  and for every hitter HR <= hits, runs >= HR, RBI >= HR, hits <= PA;
* returns the batter's joint PMF over (home_runs, hits+runs+rbi), its
  marginals, and readouts for BATTER_HOME_RUNS, BATTER_HITS_RUNS_RBI and the
  joint event (HR >= k AND H+R+RBI > line), all from one path index set so the
  two markets can never disagree with each other.

No fit, no odds, no registry/runner wiring, no validation claim. Outputs are
UNVALIDATED_RESEARCH with every authority flag False.
"""
from __future__ import annotations

from math import isfinite

from sportsedge.dfs.mlb_joint_paths import (
    MLB_JOINT_PATH_VERSION, MlbGamePathInput, MlbJointPathResult,
)
from sportsedge.source_lineage import canonical_json_sha256

HIT_FIELDS = ("singles", "doubles", "triples", "home_runs")


def _count(value, code="HRR_COUNT_INVALID"):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value < 0 or int(value) != value):
        raise ValueError(code)
    return int(value)


def _line(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value < 0):
        raise ValueError("HRR_LINE_INVALID")
    return float(value)


def validate_run_conservation(result: MlbJointPathResult, *,
                              game: MlbGamePathInput, seed: int) -> dict:
    """Return {player_id: [per-path sample]} for hitters after full checks."""
    n = result.path_count
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("HRR_PATH_COUNT_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("HRR_SEED_INVALID")
    expected_id = canonical_json_sha256({
        "version": MLB_JOINT_PATH_VERSION, "game": game.identity(),
        "path_count": n, "seed": seed,
    })
    snap = result.snapshot
    if (result.path_set_id != expected_id or snap.get("path_set_id") != expected_id
            or snap.get("path_count") != n or snap.get("game_id") != game.game_id
            or snap.get("version") != MLB_JOINT_PATH_VERSION):
        raise ValueError("HRR_PATH_IDENTITY_MISMATCH")
    games = snap.get("game_samples")
    if not isinstance(games, list) or len(games) != n or any(
            not isinstance(g, dict) for g in games):
        raise ValueError("HRR_GAME_SAMPLES_MISSING")
    team_of = {h.player_id: t.team for t in (game.away, game.home) for h in t.lineup}
    side_of = {game.away.team: "away_runs", game.home.team: "home_runs"}
    rows = snap.get("players")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("HRR_PLAYER_SET_INVALID")
    hitters = {}
    for row in rows:
        pid = row.get("player_id")
        if pid not in team_of:
            continue
        if pid in hitters:
            raise ValueError("HRR_PLAYER_DUPLICATE")
        if row.get("team") != team_of[pid] or row.get("path_set_id") != expected_id:
            raise ValueError("HRR_PLAYER_IDENTITY_MISMATCH")
        samples = row.get("samples")
        if not isinstance(samples, list) or len(samples) != n or any(
                not isinstance(s, dict) for s in samples):
            raise ValueError("HRR_PLAYER_SAMPLES_MISSING")
        hitters[pid] = samples
    if set(hitters) != set(team_of):
        raise ValueError("HRR_PLAYER_SET_INVALID")
    for i in range(n):
        runs = {t: 0 for t in side_of}
        rbi = {t: 0 for t in side_of}
        for pid, samples in hitters.items():
            s = samples[i]
            hits = sum(_count(s.get(k)) for k in HIT_FIELDS)
            hr, r, b = _count(s.get("home_runs")), _count(s.get("runs")), _count(s.get("rbi"))
            if hits > _count(s.get("plate_appearances")):
                raise ValueError("HRR_HITS_EXCEED_PA")
            if r < hr or b < hr:
                raise ValueError("HRR_HOME_RUN_ACCOUNTING_MISMATCH")
            runs[team_of[pid]] += r
            rbi[team_of[pid]] += b
        for team, key in side_of.items():
            game_runs = _count(games[i].get(key), "HRR_GAME_RUNS_INVALID")
            if runs[team] != game_runs:
                raise ValueError("HRR_RUN_CONSERVATION_MISMATCH")
            if rbi[team] > game_runs:
                raise ValueError("HRR_RBI_EXCEEDS_RUNS")
    return hitters


def read_joint_hr_hrr(result: MlbJointPathResult, *, game: MlbGamePathInput,
                      seed: int, player_id: str, hrr_line: float,
                      hr_at_least: int = 1) -> dict:
    hitters = validate_run_conservation(result, game=game, seed=seed)
    if player_id not in hitters:
        raise ValueError("HRR_PLAYER_NOT_IN_LINEUP")
    line = _line(hrr_line)
    if isinstance(hr_at_least, bool) or not isinstance(hr_at_least, int) or hr_at_least < 1:
        raise ValueError("HRR_HR_THRESHOLD_INVALID")
    n = result.path_count
    pairs = []
    for s in hitters[player_id]:
        hits = sum(int(s[k]) for k in HIT_FIELDS)
        pairs.append((int(s["home_runs"]), hits + int(s["runs"]) + int(s["rbi"])))
    joint, hr_pmf, hrr_pmf = {}, {}, {}
    for hr, hrr in pairs:
        joint[f"{hr},{hrr}"] = joint.get(f"{hr},{hrr}", 0) + 1
        hr_pmf[str(hr)] = hr_pmf.get(str(hr), 0) + 1
        hrr_pmf[str(hrr)] = hrr_pmf.get(str(hrr), 0) + 1
    norm = lambda d: {k: v / n for k, v in sorted(d.items(), key=lambda kv: tuple(map(int, kv[0].split(","))))}
    readout = {
        "player_id": player_id, "path_set_id": result.path_set_id, "path_count": n,
        "joint_pmf_hr_hrr": norm(joint),
        "home_runs_pmf": norm(hr_pmf), "hits_runs_rbi_pmf": norm(hrr_pmf),
        "p_home_runs_at_least": sum(hr >= hr_at_least for hr, _ in pairs) / n,
        "hr_at_least": hr_at_least, "hrr_line": line,
        "p_hrr_over": sum(v > line for _, v in pairs) / n,
        "p_hrr_under": sum(v < line for _, v in pairs) / n,
        "p_hrr_push": sum(v == line for _, v in pairs) / n,
        "p_joint_hr_and_hrr_over": sum(hr >= hr_at_least and v > line for hr, v in pairs) / n,
        "validation_status": "UNVALIDATED_RESEARCH",
        "production_ready": False, "promotion_authority": False,
        "model_p_authority": False, "official_authority": False,
        "source_authenticity_verified": False,
        "limitations": ["FIXED_LINEUPS_NO_SUBSTITUTIONS",
                        "CHRONOLOGICAL_BACKTEST_AND_FORWARD_REQUIRED",
                        "NOT_WIRED_TO_RUN_IT"],
    }
    readout["readout_sha256"] = canonical_json_sha256(readout)
    return readout
