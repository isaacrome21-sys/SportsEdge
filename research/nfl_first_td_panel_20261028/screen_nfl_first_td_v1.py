"""Calibration screen for NFL_FIRST_TD_V1 on the admitted panel.

Runs PREREG_NFL_FIRST_TD_FORWARD_V1_DRAFT.md section 1 exactly as
fixed there, before the panel existed:

  the construction must beat BOTH baselines on mean log loss over
  all games in the panel -- B1 (anytime-share-only: stage-2 shares
  replaced by shrunk anytime TD shares, stage 1 unchanged) and B2
  (league positional pool only) -- with the game-clustered 95% CI
  for each log-loss difference entirely below 0, AND its top-decile
  stated probabilities must not overstate realized frequency by
  more than 10 points.

Panel: 2020-2025 design seasons (seen data; an entry ticket, never
validation). A fail is FAILED_SCREEN: the construction does not
advance and returns only as a new version.

Mechanics, pinned here:
  * Candidates per team = the week's committed roster records
    (nflverse weekly rosters, status ACT) -- the design's role-gate
    source ("the week's committed roster/depth records"). Every
    rostered player carries a probability (individual shrunk share
    where history exists, positional pool otherwise, via the
    construction's own shrinkage); defensive/return outcomes are
    the DEF/ST class; the no-TD outcome is carried.
  * Games are predicted in week batches (a week's games are scored
    from strictly earlier weeks -- point-in-time).
  * Pool terms follow the Part 2 calibration convention: weeks 1-3
    use the previous season's full-season pool (2019 is the
    PRIOR_ONLY training season for 2020); counts are always
    same-season prior games.
  * CI: bootstrap over games (the cluster unit the prereg names),
    10,000 resamples, seed 20261028 (screen seed, recorded here;
    the forward test's seed is fixed at freeze per prereg section 5).
  * A realized scorer outside the candidate space (not on either
    week's roster records) is OUT_OF_SPACE: excluded from all three
    models' log-loss means equally, counted and reported.
  * A model assigning exactly zero to a realized outcome is
    infinitely wrong on that game (log loss +inf; arises for the
    no-TD outcome before a season's first no-TD game, whose
    point-in-time rate is 0 under every arm). Such games are
    tallied per model in zero_prob_realized and leave the paired
    means; no probability is floored or capped anywhere.
Research tooling only; nothing frozen; no market input anywhere.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from sportsedge.nfl_first_td_v1 import (  # noqa: E402
    DEF_RETURN_TYPES,
    History,
    position_group,
    predict_b1,
    predict_b2,
    predict_v1,
)

SEED = 20261028
RESAMPLES = 10_000
PANEL_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)
TOP_DECELE_MAX_OVERSTATEMENT = 0.10


def load_rosters(data_dir: Path):
    """(season, week, team) -> {player_id: position_group}, ACT only."""
    out = {}
    for season in (2019,) + PANEL_SEASONS:
        df = pd.read_csv(
            data_dir / f"roster_weekly_{season}.csv",
            usecols=["season", "week", "team", "position", "status",
                     "gsis_id"], low_memory=False)
        df = df[df["status"] == "ACT"]
        for (week, team), grp in df.groupby(["week", "team"]):
            out[(season, int(week), str(team))] = {
                str(pid): position_group(pos)
                for pid, pos in zip(grp["gsis_id"], grp["position"])}
    return out


def realized_key(row) -> str:
    if row["outcome"] == "NO_TD":
        return "NO_TD"
    if row["first_td_type"] in DEF_RETURN_TYPES:
        return f"DEFST:{row['first_td_team']}"
    return f"P:{row['first_td_player_id']}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--panel-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data_dir, panel_dir = Path(args.data_dir), Path(args.panel_dir)

    panel = pd.read_csv(panel_dir / "first_td_panel_2019_2025.csv",
                        dtype={"first_td_player_id": str})
    comp = pd.read_csv(panel_dir / "player_td_game_2019_2025.csv",
                       dtype={"player_id": str})
    players = pd.read_csv(data_dir / "players.csv",
                          usecols=["gsis_id", "position"])
    player_pos = {str(k): position_group(v) for k, v in
                  zip(players["gsis_id"], players["position"])}
    rosters = load_rosters(data_dir)

    comp_by_game = {gid: list(zip(g["player_id"], g["team"],
                                  g["td_type"]))
                    for gid, g in comp.groupby("game_id")}
    panel_by_season = {s: g for s, g in panel.groupby("season")}

    def group_of(season, week, team, pid):
        roster = rosters.get((season, week, team), {})
        if pid in roster:
            return roster[pid]
        return player_pos.get(pid, "OTHER")

    def fold_game(hist: History, row) -> None:
        season, week = int(row["season"]), int(row["week"])
        credits = [(pid, team, ttype,
                    group_of(season, week, team, pid))
                   for pid, team, ttype in
                   comp_by_game.get(row["game_id"], [])]
        if row["outcome"] == "NO_TD":
            first = None
        else:
            pid = str(row["first_td_player_id"])
            team = str(row["first_td_team"])
            first = (pid, team, str(row["first_td_type"]),
                     group_of(season, week, team, pid))
        hist.update_game(home=str(row["home_team"]),
                         away=str(row["away_team"]),
                         first_td=first, td_credits=credits)

    # Previous-season pool sources (full-season histories).
    prev_pools = {}
    for season in PANEL_SEASONS:
        h = History()
        for _, row in panel_by_season[season - 1].sort_values(
                ["week", "game_id"]).iterrows():
            fold_game(h, row)
        prev_pools[season] = h.pools()

    records = []
    decile_rows = []          # (stated p, realized) for the candidate
    out_of_space = []
    zero_prob = {"v1": [], "b1": [], "b2": []}
    for season in PANEL_SEASONS:
        hist = History()
        season_games = panel_by_season[season].sort_values(
            ["week", "game_id"])
        for week, batch in season_games.groupby("week"):
            week = int(week)
            pools = (prev_pools[season] if week <= 3 or hist.games == 0
                     else hist.pools())
            staged = []
            for _, row in batch.iterrows():
                home, away = str(row["home_team"]), str(row["away_team"])
                candidates = {}
                for team in (home, away):
                    roster = rosters.get((season, week, team))
                    if roster is None:  # nearest prior week with rows
                        prior = [w for (s, w, t) in rosters
                                 if s == season and t == team and w < week]
                        roster = (rosters[(season, max(prior), team)]
                                  if prior else {})
                    candidates[team] = sorted(roster.items())
                dists = {
                    "v1": predict_v1(hist, pools, home, away, candidates),
                    "b1": predict_b1(hist, pools, home, away, candidates),
                    "b2": predict_b2(pools, home, away, candidates),
                }
                key = realized_key(row)
                if key not in dists["v1"]:
                    out_of_space.append({
                        "game_id": row["game_id"], "season": season,
                        "week": week, "realized": key})
                    staged.append(row)
                    continue
                rec = {"game_id": row["game_id"], "season": season,
                       "week": week, "realized": key}
                zero_here = False
                for name, dist in dists.items():
                    if dist[key] <= 0:
                        # A model that stakes exactly zero on the
                        # realized outcome is infinitely wrong on
                        # this game (log loss +inf). Tallied per
                        # model; the game leaves the paired means
                        # (every arm's zero is reported, none is
                        # silently floored or capped).
                        zero_prob[name].append({
                            "game_id": row["game_id"], "season": season,
                            "week": week, "realized": key})
                        zero_here = True
                    else:
                        rec[f"ll_{name}"] = -math.log(dist[key])
                if not zero_here:
                    records.append(rec)
                for outcome_key, p in dists["v1"].items():
                    decile_rows.append(
                        (p, 1.0 if outcome_key == key else 0.0))
                staged.append(row)
            for row in staged:
                fold_game(hist, row)

    df = pd.DataFrame(records)
    rng = np.random.default_rng(SEED)

    def boot_ci(diffs: np.ndarray):
        n = len(diffs)
        idx = rng.integers(0, n, size=(RESAMPLES, n))
        means = diffs[idx].mean(axis=1)
        return (float(np.percentile(means, 2.5)),
                float(np.percentile(means, 97.5)))

    results = {"seed": SEED, "resamples": RESAMPLES,
               "games_scored": int(len(df)),
               "out_of_space": out_of_space,
               "zero_prob_realized": {
                   m: {"count": len(v), "games": v}
                   for m, v in zero_prob.items()},
               "mean_log_loss": {
                   m: float(df[f"ll_{m}"].mean())
                   for m in ("v1", "b1", "b2")}}
    for base in ("b1", "b2"):
        diffs = (df["ll_v1"] - df[f"ll_{base}"]).to_numpy()
        lo, hi = boot_ci(diffs)
        results[f"delta_vs_{base}"] = {
            "mean": float(diffs.mean()), "ci95": [lo, hi],
            "criterion_pass": bool(hi < 0)}
    # Decile calibration of the construction's stated probabilities.
    probs = np.array([p for p, _ in decile_rows])
    realized = np.array([r for _, r in decile_rows])
    order = np.argsort(-probs, kind="mergesort")
    deciles = []
    n = len(probs)
    for d in range(10):
        sl = order[d * n // 10:(d + 1) * n // 10]
        deciles.append({
            "decile": d + 1,
            "mean_stated": float(probs[sl].mean()),
            "realized_rate": float(realized[sl].mean()),
            "n": int(len(sl))})
    top = deciles[0]
    over = top["mean_stated"] - top["realized_rate"]
    results["deciles"] = deciles
    results["top_decile"] = {
        **top, "overstatement": float(over),
        "criterion_pass": bool(over <= TOP_DECELE_MAX_OVERSTATEMENT)}
    results["per_season_delta"] = {
        str(s): {
            base: float((g["ll_v1"] - g[f"ll_{base}"]).mean())
            for base in ("b1", "b2")}
        for s, g in df.groupby("season")}
    passed = (results["delta_vs_b1"]["criterion_pass"]
              and results["delta_vs_b2"]["criterion_pass"]
              and results["top_decile"]["criterion_pass"])
    results["verdict"] = "SCREEN_PASS" if passed else "FAILED_SCREEN"
    Path(args.out).write_text(json.dumps(results, indent=1) + "\n")
    print(json.dumps({k: results[k] for k in (
        "games_scored", "mean_log_loss", "delta_vs_b1", "delta_vs_b2",
        "top_decile", "verdict")}, indent=1))
    print("out_of_space:", len(out_of_space), out_of_space[:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
