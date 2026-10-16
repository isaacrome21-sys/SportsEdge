"""Scorer for PREREG MLB_TOTAL_HITS_JOINT_PATH_HARNESS_V1 — fold 2025.

Executes the frozen preregistration exactly:
  * candidate = locked construction (readout blob 029829688..., path source
    blob 50e027bc0...), asserted at runtime from this working tree;
  * 10,000 paths per game, seed = int.from_bytes(SHA-256(
    "MLB_TOTAL_HITS_JOINT_PATH_HARNESS_PREREG_V1|" + game_id)[:8], "big");
  * simulator inputs fitted with the repo's own fitter
    (sportsedge/dfs/mlb_joint_path_fitter.py) under the manifest's declared
    policy: batter profiles per game from PAs strictly before the game's
    official date; hook surface + baserunning profile once from the fold's
    training window (league context fits);
  * baselines on identical rows, all PIT: naive_team_rate_poisson,
    league_constant_rate, trailing_20_game_team_rate,
    independence_convolution (definitions in the dataset manifest).

Fold 2024 is NOT scored here: its frozen training window (all games strictly
before 2024-01-01) is absent from the archived data the preregistration
restricts scoring to, so its typical lines and training-window baselines are
undefined. See the manifest and RESULTS.md.

Usage: score_fold.py <data_dir> <manifest.json> <work_dir> [workers]
Outputs in <work_dir>: bundles.pkl, pmf_rows.jsonl (checkpointed),
exclusions.jsonl, score_log.txt.
"""
from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import pickle
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from sportsedge.dfs.mlb_joint_path_fitter import (  # noqa: E402
    HistoricalBaserunningOpportunity, HistoricalHookOpportunity,
    HistoricalPlateAppearance, MlbJointPathFitPolicy, fit_baserunning_profile,
    fit_hook_hazard_surface, fit_plate_appearance_profile)
from sportsedge.dfs.mlb_joint_paths import (  # noqa: E402
    BaserunningProfile, HitterPathInput, HookHazardSurface, MlbGamePathInput,
    PlateAppearanceProfile, TeamPathInput, simulate_mlb_joint_paths)
from sportsedge.research.mlb_joint_total_hits import read_joint_total_hits  # noqa: E402

PREREG_SHA256 = "9080d16804ed9188083747a78b70520268cd2880ca303955256c65154a62a51b"
READOUT_BLOB = "029829688817cfca4f1362dc2bdbe806dbaab42c"
PATHS_BLOB = "50e027bc0a5551b2de9096292cc1c460567d5b63"
PATH_COUNT = 10000
SCHEMA = "MLB_TOTAL_HITS_JOINT_PATH_HARNESS_PREREG_V1"
TRAIN_END = "2025-01-01"  # fold 2025 training window: dates < this


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def assert_frozen_identities() -> dict:
    prereg = REPO / "research/mlb_total_hits_joint_path_harness/PREREG_MLB_TOTAL_HITS_JOINT_PATH_HARNESS_V1.md"
    got = hashlib.sha256(prereg.read_bytes()).hexdigest()
    if got != PREREG_SHA256:
        raise SystemExit(f"PREREG HASH MISMATCH: {got}")
    readout = REPO / "sportsedge/research/mlb_joint_total_hits.py"
    paths = REPO / "sportsedge/dfs/mlb_joint_paths.py"
    if git_blob_sha(readout) != READOUT_BLOB:
        raise SystemExit("READOUT MODULE BLOB MISMATCH — construction differs from freeze")
    if git_blob_sha(paths) != PATHS_BLOB:
        raise SystemExit("PATH SOURCE BLOB MISMATCH — construction differs from freeze")
    return {"prereg_sha256": got, "readout_blob": READOUT_BLOB,
            "paths_blob": PATHS_BLOB,
            "fitter_blob": git_blob_sha(REPO / "sportsedge/dfs/mlb_joint_path_fitter.py")}


def d2ord(date_str: str) -> int:
    y, m, d = (int(x) for x in date_str.split("-"))
    return datetime(y, m, d, tzinfo=timezone.utc).toordinal()


def dt_of(date_str: str) -> datetime:
    y, m, d = (int(x) for x in date_str.split("-"))
    return datetime(y, m, d, tzinfo=timezone.utc)


def poisson_pmf(lam: float, kmax: int = 80) -> dict:
    if lam <= 0:
        return {0: 1.0}
    pmf, total = {}, 0.0
    for k in range(kmax + 1):
        p = math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))
        pmf[k] = p
        total += p
    return {k: p / total for k, p in pmf.items()}


def convolve(p: dict, q: dict) -> dict:
    out = defaultdict(float)
    for a, pa in p.items():
        for b, pb in q.items():
            out[a + b] += pa * pb
    return dict(out)


def emp_pmf(counter: Counter) -> dict:
    n = sum(counter.values())
    return {k: v / n for k, v in sorted(counter.items())}


def build_bundles(data_dir: Path, manifest: dict, work_dir: Path) -> list:
    """Serial PIT precompute: league fits, per-game profiles + baselines."""
    policy_cfg = manifest["fit_policy"]
    games = [json.loads(x) for x in (data_dir / "games.jsonl").read_text().splitlines()]
    games_by_id = {g["game_id"]: g for g in games}
    scored_ids = set(manifest["scored_game_ids"])
    file_hash = {}
    cache = Path.home() / "workspace/tmp/bt_data"
    for g in games:
        for kind, pat in (("box", "boxscore_cache/{}.json"), ("pbp", "pbp_cache/pbp_{}.json")):
            p = cache / pat.format(g["game_id"])
            file_hash[(g["game_id"], kind)] = hashlib.sha256(p.read_bytes()).hexdigest()

    # ---- PA history per (batter, role), date-sorted
    pa_hist: dict = defaultdict(list)
    with gzip.open(data_dir / "pa_rows.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            pa_hist[(r["b"], r["r"])].append((d2ord(r["d"]), r["o"], r["p"], r["g"]))
    for key in pa_hist:
        pa_hist[key].sort()
    pa_dates = {k: [x[0] for x in v] for k, v in pa_hist.items()}

    def fit_profile(batter: int, role: str, game_date: str, policy) -> PlateAppearanceProfile:
        key = (batter, role)
        rows = pa_hist.get(key, [])
        k = bisect.bisect_left(pa_dates.get(key, []), d2ord(game_date))
        obs = [HistoricalPlateAppearance(
            occurred_at=dt_of_idx(d), batter_id=str(batter), pitcher_role=role,
            outcome=o, pitch_count=p, source_sha256=file_hash[(str(g), "pbp")])
            for d, o, p, g in rows[:k]]
        return fit_plate_appearance_profile(
            obs, policy=policy, batter_id=str(batter), pitcher_role=role,
            source_label=f"TH_V1_{role}")

    def dt_of_idx(ordinal: int) -> datetime:
        return datetime.fromordinal(ordinal, tz=timezone.utc)

    # ---- league context fits on the training window (dates < TRAIN_END)
    train_policy = MlbJointPathFitPolicy(
        policy_id=policy_cfg["policy_id"], status="FROZEN",
        cutoff_at=dt_of(TRAIN_END), min_pa=policy_cfg["min_pa"],
        min_hook_cell_trials=policy_cfg["min_hook_cell_trials"],
        min_baserunning_opportunities=policy_cfg["min_baserunning_opportunities"],
        pitch_count_upper_bounds=tuple(policy_cfg["pitch_count_upper_bounds"]),
        runs_allowed_upper_bounds=tuple(policy_cfg["runs_allowed_upper_bounds"]))
    hook_obs = []
    with gzip.open(data_dir / "hook_rows.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            if r["d"] < TRAIN_END:
                hook_obs.append(HistoricalHookOpportunity(
                    occurred_at=dt_of(r["d"]), cumulative_pitch_count=r["p"],
                    cumulative_runs_allowed=r["r"],
                    removed_before_next_batter=bool(r["x"]),
                    source_sha256=file_hash[(str(r["g"]), "pbp")]))
    hook_surface = fit_hook_hazard_surface(hook_obs, policy=train_policy,
                                           source_label="TH_V1_HOOK")
    base_obs = []
    with gzip.open(data_dir / "baserun_rows.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            if r["d"] < TRAIN_END:
                base_obs.append(HistoricalBaserunningOpportunity(
                    occurred_at=dt_of(r["d"]), kind=r["k"], success=bool(r["s"]),
                    source_sha256=file_hash[(str(r["g"]), "pbp")]))
    baserunning = fit_baserunning_profile(base_obs, policy=train_policy,
                                          source_label="TH_V1_BASERUN")
    (work_dir / "league_fits.json").write_text(json.dumps({
        "hook_surface": hook_surface.identity(),
        "baserunning": baserunning.identity(),
        "hook_obs": len(hook_obs), "baserun_obs": len(base_obs)}, indent=1))

    # ---- league_constant_rate PMFs from the training window
    train_games = [g for g in games if g["date"] < TRAIN_END]
    team_counter = Counter()
    game_counter = Counter()
    for g in train_games:
        team_counter[g["away_hits"]] += 1
        team_counter[g["home_hits"]] += 1
        game_counter[g["away_hits"] + g["home_hits"]] += 1
    league_team_pmf = emp_pmf(team_counter)
    league_game_pmf = emp_pmf(game_counter)

    # ---- team hit histories (expanding PIT) + batter starter-game hits
    team_hist: dict = defaultdict(list)
    for g in sorted(games, key=lambda x: (x["date"], x["game_id"])):
        team_hist[g["away_team"]].append((d2ord(g["date"]), g["away_hits"]))
        team_hist[g["home_team"]].append((d2ord(g["date"]), g["home_hits"]))
    team_dates = {t: [x[0] for x in v] for t, v in team_hist.items()}

    def team_rate(team: str, date_ord: int, last_n: int | None) -> float:
        rows = team_hist[team]
        k = bisect.bisect_left(team_dates[team], date_ord)
        window = rows[:k] if last_n is None else rows[max(0, k - last_n):k]
        return sum(h for _, h in window) / len(window)

    batter_starts: dict = defaultdict(list)   # batter -> [(date_ord, hits)]
    pooled_starts: list = []                  # (date_ord, hits) all starters
    with gzip.open(data_dir / "batter_games.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            if r["s"] == 1:
                batter_starts[r["b"]].append((d2ord(r["d"]), r["h"]))
                pooled_starts.append((d2ord(r["d"]), r["h"]))
    for key in batter_starts:
        batter_starts[key].sort()
    pooled_starts.sort()
    pooled_dates = [x[0] for x in pooled_starts]
    batter_dates = {b: [x[0] for x in v] for b, v in batter_starts.items()}

    def batter_marginal(batter: int, date_ord: int) -> dict:
        rows = batter_starts.get(batter, [])
        k = bisect.bisect_left(batter_dates.get(batter, []), date_ord)
        if k == 0:
            kp = bisect.bisect_left(pooled_dates, date_ord)
            return emp_pmf(Counter(h for _, h in pooled_starts[:kp]))
        return emp_pmf(Counter(h for _, h in rows[:k]))

    # ---- per-game bundles for scored games (date order)
    exclusions = []
    bundles = []
    scored_games = sorted((games_by_id[i] for i in scored_ids),
                          key=lambda x: (x["date"], x["game_id"]))
    for g in scored_games:
        date_ord = d2ord(g["date"])
        policy = MlbJointPathFitPolicy(
            policy_id=policy_cfg["policy_id"], status="FROZEN",
            cutoff_at=dt_of(g["date"]), min_pa=policy_cfg["min_pa"],
            min_hook_cell_trials=policy_cfg["min_hook_cell_trials"],
            min_baserunning_opportunities=policy_cfg["min_baserunning_opportunities"],
            pitch_count_upper_bounds=tuple(policy_cfg["pitch_count_upper_bounds"]),
            runs_allowed_upper_bounds=tuple(policy_cfg["runs_allowed_upper_bounds"]))
        profiles, fail = {}, None
        for side in ("away", "home"):
            for pid in g[f"{side}_lineup"]:
                for role in ("STARTER", "BULLPEN"):
                    try:
                        prof = fit_profile(pid, role, g["date"], policy)
                    except Exception as exc:  # fitter gate (min_pa etc.)
                        fail = f"{type(exc).__name__}:{exc}"
                        break
                    profiles[f"{pid}|{role}"] = {
                        "outcomes": dict(prof.outcome_probabilities),
                        "pitches": {int(k): v for k, v in prof.pitch_count_probabilities.items()},
                        "source_id": prof.source_id}
                if fail:
                    break
            if fail:
                break
        if fail:
            exclusions.append({"game_id": g["game_id"], "reason": "PROFILE_FIT_FAILED",
                               "detail": fail})
            continue
        # baselines on identical rows
        lam = {side: team_rate(g[f"{side}_team"], date_ord, None) for side in ("away", "home")}
        lam20 = {side: team_rate(g[f"{side}_team"], date_ord, 20) for side in ("away", "home")}
        conv = {}
        for side in ("away", "home"):
            acc = {0: 1.0}
            for pid in g[f"{side}_lineup"]:
                acc = convolve(acc, batter_marginal(pid, date_ord))
            conv[side] = acc
        baselines = {
            "naive_team_rate_poisson": {
                "away": poisson_pmf(lam["away"]), "home": poisson_pmf(lam["home"]),
                "game": poisson_pmf(lam["away"] + lam["home"])},
            "league_constant_rate": {
                "away": league_team_pmf, "home": league_team_pmf,
                "game": league_game_pmf},
            "trailing_20_game_team_rate": {
                "away": poisson_pmf(lam20["away"]), "home": poisson_pmf(lam20["home"]),
                "game": poisson_pmf(lam20["away"] + lam20["home"])},
            "independence_convolution": {
                "away": conv["away"], "home": conv["home"],
                "game": convolve(conv["away"], conv["home"])},
        }
        seed = int.from_bytes(hashlib.sha256(
            f"{SCHEMA}|{g['game_id']}".encode()).digest()[:8], "big")
        bundles.append({
            "game_id": g["game_id"], "date": g["date"],
            "away_team": g["away_team"], "home_team": g["home_team"],
            "away_lineup": g["away_lineup"], "home_lineup": g["home_lineup"],
            "away_starter": g["away_starter"], "home_starter": g["home_starter"],
            "realized": {"away": g["away_hits"], "home": g["home_hits"],
                         "game": g["away_hits"] + g["home_hits"]},
            "profiles": profiles, "baselines": baselines, "seed": seed,
            "hook_surface": hook_surface.identity(),
            "baserunning": baserunning.identity(),
        })
    (work_dir / "exclusions.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in exclusions))
    with open(work_dir / "bundles.pkl", "wb") as fh:
        pickle.dump({"bundles": bundles,
                     "hook_surface": hook_surface.identity(),
                     "baserunning": baserunning.identity()}, fh)
    return bundles


def _profile(spec: dict) -> PlateAppearanceProfile:
    return PlateAppearanceProfile(
        outcome_probabilities={k: float(v) for k, v in spec["outcomes"].items()},
        pitch_count_probabilities={int(k): float(v) for k, v in spec["pitches"].items()},
        source_id=spec["source_id"])


def simulate_game(bundle: dict) -> dict:
    hs = bundle["hook_surface"]
    hook = HookHazardSurface(
        pitch_count_upper_bounds=tuple(hs["pitch_count_upper_bounds"]),
        runs_allowed_upper_bounds=tuple(hs["runs_allowed_upper_bounds"]),
        remove_probabilities=tuple(tuple(r) for r in hs["remove_probabilities"]),
        source_id=hs["source_id"])
    br = bundle["baserunning"]
    baserunning = BaserunningProfile(
        single_second_scores=br["single_second_scores"],
        single_first_to_third=br["single_first_to_third"],
        double_first_scores=br["double_first_scores"], source_id=br["source_id"])

    def team_input(side: str) -> TeamPathInput:
        lineup = tuple(
            HitterPathInput(
                player_id=str(pid),
                starter_profile=_profile(bundle["profiles"][f"{pid}|STARTER"]),
                bullpen_profile=_profile(bundle["profiles"][f"{pid}|BULLPEN"]))
            for pid in bundle[f"{side}_lineup"])
        return TeamPathInput(team=bundle[f"{side}_team"], lineup=lineup,
                             starter_player_id=str(bundle[f"{side}_starter"]),
                             hook_surface=hook)

    game = MlbGamePathInput(
        rules_mode="REGULAR_SEASON", game_id=bundle["game_id"],
        away=team_input("away"), home=team_input("home"),
        baserunning=baserunning, updated_at=dt_of(bundle["date"]),
        source_id="MLB_TOTAL_HITS_HARNESS_V1")
    result = simulate_mlb_joint_paths(game, path_count=PATH_COUNT, seed=bundle["seed"])

    def pmf(market: str, team: str | None) -> dict:
        readout = read_joint_total_hits(
            result, game=game, seed=bundle["seed"], market=market,
            side="OVER", line=0.5, team=team)
        return {int(k): v for k, v in readout["count_pmf"].items()}, readout["readout_sha256"]

    game_pmf, game_sha = pmf("GAME_TOTAL_HITS", None)
    away_pmf, away_sha = pmf("TEAM_TOTAL_HITS", bundle["away_team"])
    home_pmf, home_sha = pmf("TEAM_TOTAL_HITS", bundle["home_team"])
    return {
        "game_id": bundle["game_id"], "date": bundle["date"],
        "away_team": bundle["away_team"], "home_team": bundle["home_team"],
        "realized": bundle["realized"], "seed": bundle["seed"],
        "path_set_id": result.path_set_id,
        "readout_sha256": {"game": game_sha, "away": away_sha, "home": home_sha},
        "candidate": {"game": game_pmf, "away": away_pmf, "home": home_pmf},
        "baselines": bundle["baselines"],
    }


def main() -> None:
    data_dir, manifest_path, work_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    work_dir.mkdir(parents=True, exist_ok=True)
    identities = assert_frozen_identities()
    manifest = json.loads(manifest_path.read_text())
    manifest_sha = hashlib.sha256(json.dumps(
        {k: v for k, v in manifest.items() if k != "manifest_sha256"},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if manifest_sha != manifest["manifest_sha256"]:
        raise SystemExit("MANIFEST HASH MISMATCH vs its recorded sha256")
    log = (work_dir / "score_log.txt").open("a")
    print(f"identities OK: {identities}; manifest {manifest_sha}", file=log, flush=True)

    bundles_file = work_dir / "bundles.pkl"
    if bundles_file.exists():
        bundles = pickle.loads(bundles_file.read_bytes())["bundles"]
        print(f"loaded {len(bundles)} bundles from checkpoint", file=log, flush=True)
    else:
        t0 = time.time()
        bundles = build_bundles(data_dir, manifest, work_dir)
        print(f"built {len(bundles)} bundles in {time.time()-t0:.0f}s", file=log, flush=True)

    out_path = work_dir / "pmf_rows.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["game_id"])
    todo = [b for b in bundles if b["game_id"] not in done]
    print(f"simulating {len(todo)} games ({len(done)} already done)", file=log, flush=True)
    t0 = time.time()
    n0 = len(done)
    with open(out_path, "a") as out:
        if workers > 1 and len(todo) > 1:
            from multiprocessing import Pool
            with Pool(workers) as pool:
                for i, row in enumerate(pool.imap_unordered(simulate_game, todo), 1):
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    if i % 25 == 0:
                        el = time.time() - t0
                        rate = i / el
                        print(f"{n0+i}/{len(bundles)} games, {el:.0f}s elapsed, "
                              f"eta {(len(todo)-i)/rate/60:.1f} min", file=log, flush=True)
        else:
            for i, b in enumerate(todo, 1):
                out.write(json.dumps(simulate_game(b)) + "\n")
                out.flush()
                if i % 5 == 0:
                    print(f"{n0+i}/{len(bundles)} games", file=log, flush=True)
    print(f"DONE {len(bundles)} games in {time.time()-t0:.0f}s", file=log, flush=True)
    log.close()


if __name__ == "__main__":
    main()
