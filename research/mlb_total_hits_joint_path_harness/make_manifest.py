"""Build + hash the dataset manifest required by PREREG V1 section 6.

Runs BEFORE any scoring. Records: dataset file hashes, fold definitions,
the scored-row set for fold 2025 with per-game row hashes, structural and
profile-count eligibility (the profile gate counted exactly: prior PAs per
batter-role >= min_pa), the declared fit policy (hook bins validated on
training-window cell counts), typical lines from the training window only,
and fold 2024's status (training window absent from the archive).

Usage: make_manifest.py <data_dir> <manifest_out.json>
"""
from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

MIN_PA = 25
MIN_BASERUN_OPPS = 100
GAME_GRID = [x + 0.5 for x in range(21)]
TEAM_GRID = [x + 0.5 for x in range(13)]


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def nearest_line(median: float, grid: list) -> float:
    return min(grid, key=lambda L: (abs(L - median), L))  # ties -> lower line


def bucket(value: int, bounds) -> int:
    for i, b in enumerate(bounds):
        if value <= b:
            return i
    raise ValueError(value)


def main() -> None:
    data_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    cache = Path.home() / "workspace/tmp/bt_data"
    games = [json.loads(x) for x in (data_dir / "games.jsonl").read_text().splitlines()]
    extraction = json.loads((data_dir / "extraction_report.json").read_text())
    hits_bad = set(extraction["hits_mismatch"])

    # ---- hook cell counts on the training window (dates < 2025-01-01)
    pitch_bounds = [55, 70, 85, 100, 200]
    run_bounds = [1, 2, 3, 4, 20]
    cells = Counter()
    n_hook_train = 0
    with gzip.open(data_dir / "hook_rows.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            if r["d"] < "2025-01-01":
                cells[(bucket(r["p"], pitch_bounds), bucket(r["r"], run_bounds))] += 1
                n_hook_train += 1
    min_cell = min(cells.get((i, j), 0)
                   for i in range(len(pitch_bounds)) for j in range(len(run_bounds)))
    min_hook_trials = 50 if min_cell >= 50 else 25

    # ---- PA counts per (batter, role) by date for the profile gate
    pa_hist: dict = defaultdict(list)
    with gzip.open(data_dir / "pa_rows.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            pa_hist[(r["b"], r["r"])].append(r["d"])
    for key in pa_hist:
        pa_hist[key].sort()

    def prior_pa(batter: int, role: str, date: str) -> int:
        rows = pa_hist.get((batter, role), [])
        return bisect.bisect_left(rows, date)

    # ---- eligibility + scored rows for fold 2025
    scored, excluded = [], []
    row_hashes = {}
    for g in sorted((g for g in games if g["season"] == 2025),
                    key=lambda x: (x["date"], x["game_id"])):
        gid = g["game_id"]
        ids = g["away_lineup"] + g["home_lineup"] + [g["away_starter"], g["home_starter"]]
        if not g["lineup_complete"]:
            excluded.append({"game_id": gid, "reason": "LINEUP_OR_STARTER_INCOMPLETE"})
            continue
        if len(set(ids)) != 20:
            excluded.append({"game_id": gid, "reason": "PLAYER_ID_COLLISION"})
            continue
        if gid in hits_bad or str(gid) in hits_bad:
            excluded.append({"game_id": gid, "reason": "PBP_BOXSCORE_HITS_MISMATCH"})
            continue
        gate_fail = None
        for pid in g["away_lineup"] + g["home_lineup"]:
            for role in ("STARTER", "BULLPEN"):
                if prior_pa(pid, role, g["date"]) < MIN_PA:
                    gate_fail = {"batter": pid, "role": role,
                                 "prior_pa": prior_pa(pid, role, g["date"])}
                    break
            if gate_fail:
                break
        if gate_fail:
            excluded.append({"game_id": gid, "reason": "PROFILE_MIN_PA_NOT_MET",
                             "detail": gate_fail})
            continue
        scored.append(gid)
        row_hashes[gid] = canonical_hash({
            "game_id": gid, "date": g["date"],
            "away_lineup": g["away_lineup"], "home_lineup": g["home_lineup"],
            "away_starter": g["away_starter"], "home_starter": g["home_starter"],
            "away_hits": g["away_hits"], "home_hits": g["home_hits"],
            "box_sha256": sha_file(cache / f"boxscore_cache/{gid}.json"),
            "pbp_sha256": sha_file(cache / f"pbp_cache/pbp_{gid}.json")})

    # ---- typical lines from the fold-2025 training window (2024 games)
    train = [g for g in games if g["date"] < "2025-01-01"]
    game_totals = [g["away_hits"] + g["home_hits"] for g in train]
    team_totals = [g["away_hits"] for g in train] + [g["home_hits"] for g in train]
    med_game = statistics.median(game_totals)
    med_team = statistics.median(team_totals)

    pre2024 = [g for g in games if g["date"] < "2024-01-01"]
    manifest = {
        "schema": "MLB_TOTAL_HITS_JOINT_PATH_HARNESS_PREREG_V1",
        "dataset": {
            "source": "StatsAPI archived acquisition (boxscore_cache + pbp_cache, "
                      "~/workspace/tmp/bt_data), schedules pbp_cache/schedule_{2024,2025}.json",
            "files": {name: sha_file(data_dir / name) for name in
                      ("games.jsonl", "pa_rows.jsonl.gz", "hook_rows.jsonl.gz",
                       "baserun_rows.jsonl.gz", "batter_games.jsonl.gz",
                       "extraction_report.json")},
            "games_parsed": extraction["games_parsed"],
            "hits_mismatch_games": len(extraction["hits_mismatch"]),
            "pa_rows": extraction["pa_rows"], "hook_rows": extraction["hook_rows"],
            "baserun_rows": extraction["baserun_rows"],
        },
        "pit_rule": "All simulator inputs, baseline inputs and rates for a game "
                    "use only archived games with officialDate strictly before "
                    "that game's officialDate. PA occurred_at = source game's "
                    "officialDate 00:00 UTC; cutoff = prediction game's "
                    "officialDate 00:00 UTC.",
        "lineup_provenance": "Official starting batting order (slots x00) and "
                             "gamesStarted==1 starter from the official boxscore "
                             "record; games lacking a complete 9-man order or a "
                             "unique starter are excluded, never imputed.",
        "fit_policy": {
            "policy_id": "MLB_TOTAL_HITS_HARNESS_FIT_V1", "status": "FROZEN",
            "min_pa": MIN_PA, "min_hook_cell_trials": min_hook_trials,
            "min_baserunning_opportunities": MIN_BASERUN_OPPS,
            "pitch_count_upper_bounds": pitch_bounds,
            "runs_allowed_upper_bounds": run_bounds,
            "hook_cell_min_trials_training_window": int(min_cell),
            "hook_training_rows": n_hook_train,
            "league_context_fit_scope": "hook surface + baserunning profile fit "
                                        "once per fold on the training window",
            "batter_profile_scope": "per game, expanding, strictly prior dates",
        },
        "folds": {
            "2025": {
                "training_window": "archived R games with officialDate < 2025-01-01",
                "training_games": len(train),
                "scoring_window_games": len([g for g in games if g["season"] == 2025]),
                "scored_game_ids": scored,
                "excluded": excluded,
                "typical_lines": {
                    "GAME_TOTAL_HITS": nearest_line(med_game, GAME_GRID),
                    "TEAM_TOTAL_HITS": nearest_line(med_team, TEAM_GRID),
                    "training_median_game_hits": med_game,
                    "training_median_team_hits": med_team,
                },
                "row_hashes": row_hashes,
            },
            "2024": {
                "status": "NOT_SCOREABLE_AS_FROZEN",
                "reason": "Frozen training window = all eligible games strictly "
                          "before 2024-01-01; the section-6 archive contains "
                          "zero such games (earliest archived game 2024-03-20), "
                          "so the fold's typical lines and training-window "
                          "baselines (league_constant_rate) are undefined and "
                          "no batter has prior PA data at the window boundary. "
                          "Substituting a within-season burn-in would be a "
                          "different, unfrozen harness; not done.",
                "archived_games_before_2024_01_01": len(pre2024),
            },
        },
    }
    manifest["manifest_sha256"] = canonical_hash(
        {k: v for k, v in manifest.items() if k != "manifest_sha256"})
    out_path.write_text(json.dumps(manifest, indent=1))
    print("scored:", len(scored), "| excluded:", len(excluded),
          "| manifest_sha256:", manifest["manifest_sha256"])
    print("typical lines:", manifest["folds"]["2025"]["typical_lines"])
    print("hook min cell:", min_cell, "-> min_hook_cell_trials:", min_hook_trials)


if __name__ == "__main__":
    main()
