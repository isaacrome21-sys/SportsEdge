#!/usr/bin/env python3
"""SCREEN REPRODUCTION — NFL_TEAM_TOTAL_DIST_V1 with the BUILT engine.

Re-runs the design screen of research/nfl_activation_20261027
(SCREEN_REPORT.md) using the committed engine
``sportsedge/nfl_team_total_dist.py`` — not the design script — on the
same input, under the criteria fixed in the design script's header
before its run:

  Team totals pass iff pooled candidate MAE < B1 and < B2 AND pooled
  CRPS < B1 and < B2 AND no test season's candidate MAE is worse than
  its B2 MAE by more than 0.25.

The design reference numbers are the design run's own output, copied
verbatim into DESIGN_SCREEN_RESULTS_REFERENCE.json in this directory
(provenance: draft PR #2852, screen_results_v1.json, generated
2026-10-28T04:26:26Z). The implied-split column is a DESIGN-ONLY
diagnostic (untimestamped nflverse closing snapshot, gap G7): it is
reproduced for comparison against the design's disclosure and is never
a verdict. The engine itself takes no market input; spread/total are
read here, in the harness only, solely for that diagnostic.

Usage:
  python3 reproduce_screen_with_engine.py --games /path/to/games.csv.gz \
      [--out screen_reproduction_results.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sportsedge.nfl_team_total_dist import (  # noqa: E402
    GameRecord, TeamTotalDistEngine, crps_from_cdf, derive_pooled_cv,
    nb_cdf_grid)

TEST_SEASONS = tuple(range(2020, 2026))
HERE = os.path.dirname(os.path.abspath(__file__))


def metrics(rows: list[dict], c: float) -> dict:
    out = {"n": int(len(rows))}
    for col in ("mu", "b1", "b2"):
        out[f"mae_{col}"] = float(np.mean(
            [abs(r[col] - r["score"]) for r in rows]))
    sub = [r for r in rows if r.get("implied") is not None]
    out["n_implied"] = int(len(sub))
    out["mae_implied"] = float(np.mean(
        [abs(r["implied"] - r["score"]) for r in sub])) if sub else None
    cr = {"mu": [], "b1": [], "b2": []}
    pit = []
    inside90 = []
    for r in rows:
        for col in ("mu", "b1", "b2"):
            cr[col].append(crps_from_cdf(nb_cdf_grid(r[col], c),
                                         r["score"]))
        cdf = nb_cdf_grid(r["mu"], c)
        pit.append(float(cdf[min(r["score"], 120)]))
        lo = int(np.searchsorted(cdf, 0.05))
        hi = int(np.searchsorted(cdf, 0.95))
        inside90.append(lo <= r["score"] <= hi)
    for col in ("mu", "b1", "b2"):
        out[f"crps_{col}"] = float(np.mean(cr[col]))
    out["pit_mean"] = float(np.mean(pit))
    out["inside90_share"] = float(np.mean(inside90))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True,
                    help="path to nflverse games.csv.gz")
    ap.add_argument("--out", default=os.path.join(
        HERE, "screen_reproduction_results.json"))
    args = ap.parse_args()

    raw = open(args.games, "rb").read()
    games_sha = hashlib.sha256(raw).hexdigest()
    games = pd.read_csv(args.games, low_memory=False)

    records: dict[str, GameRecord] = {}
    harness_rows = games.to_dict("records")
    for r in harness_rows:
        rec = GameRecord(
            season=int(r["season"]), week=int(r["week"]),
            gameday=str(r["gameday"]), game_id=str(r["game_id"]),
            home_team=str(r["home_team"]), away_team=str(r["away_team"]),
            home_score=(None if pd.isna(r["home_score"])
                        else int(r["home_score"])),
            away_score=(None if pd.isna(r["away_score"])
                        else int(r["away_score"])),
            game_type=str(r["game_type"]))
        records[rec.game_id] = rec

    # The training constant, re-derived with the built engine.
    c = derive_pooled_cv(records.values())

    # Walk-forward with the built engine; predictions precede recording.
    engine = TeamTotalDistEngine()
    rows = []
    processed = engine.process_snapshot(records.values())
    for game, home_pred, away_pred in processed:
        if game.season not in TEST_SEASONS:
            continue
        for pred, score in ((home_pred, int(game.home_score)),
                            (away_pred, int(game.away_score))):
            rows.append({"season": game.season, "week": game.week,
                         "game_id": game.game_id, "team": pred.team,
                         "score": score, "mu": pred.mu,
                         "b1": pred.b1_team_mean,
                         "b2": pred.b2_league_mean})

    # Implied-split diagnostic (DESIGN-ONLY; harness-side market data).
    gdf = games[games["season"].isin(TEST_SEASONS)].copy()
    gdf = gdf.dropna(subset=["spread_line", "total_line"])
    margin = gdf["home_score"] - gdf["away_score"]
    corr = float(np.corrcoef(gdf["spread_line"], margin)[0, 1])
    sign = 1.0 if corr > 0 else -1.0
    implied = {}
    for r in gdf.itertuples():
        imp_margin = sign * float(r.spread_line)
        implied[(r.game_id, r.home_team)] = \
            (float(r.total_line) + imp_margin) / 2
        implied[(r.game_id, r.away_team)] = \
            (float(r.total_line) - imp_margin) / 2
    for r in rows:
        r["implied"] = implied.get((r["game_id"], r["team"]))

    pooled = metrics(rows, c)
    per_season = {int(s): metrics([r for r in rows if r["season"] == s], c)
                  for s in TEST_SEASONS}
    passed = (
        pooled["mae_mu"] < pooled["mae_b1"]
        and pooled["mae_mu"] < pooled["mae_b2"]
        and pooled["crps_mu"] < pooled["crps_b1"]
        and pooled["crps_mu"] < pooled["crps_b2"]
        and all(per_season[s]["mae_mu"] <= per_season[s]["mae_b2"] + 0.25
                for s in per_season)
    )

    ref = json.load(open(os.path.join(
        HERE, "DESIGN_SCREEN_RESULTS_REFERENCE.json")))
    ref_tt = ref["team_totals"]

    def delta_block(mine: dict, theirs: dict) -> dict:
        keys = ["n", "mae_mu", "mae_b1", "mae_b2", "n_implied",
                "mae_implied", "crps_mu", "crps_b1", "crps_b2",
                "pit_mean", "inside90_share"]
        return {k: (mine[k] - theirs[k]) for k in keys}

    report = {
        "kind": "DESIGN_SCREEN_REPRODUCTION_WITH_BUILT_ENGINE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "sportsedge/nfl_team_total_dist.py (NFL_TEAM_TOTAL_DIST_V1)",
        "inputs_sha256": {"games_csv_gz": games_sha},
        "design_input_sha256": ref["inputs_sha256"]["games_csv_gz"],
        "input_matches_design_pull": bool(
            games_sha == ref["inputs_sha256"]["games_csv_gz"]),
        "pooled_cv_c": c,
        "design_pooled_cv_c": ref_tt["pooled_cv_c"],
        "pooled_cv_c_delta": c - ref_tt["pooled_cv_c"],
        "spread_sign_empirical": {
            "corr_spread_vs_home_margin": corr, "sign_applied": sign},
        "pooled": pooled,
        "per_season": {str(k): v for k, v in per_season.items()},
        "screen_pass": bool(passed),
        "design_screen_pass": bool(ref_tt["screen_pass"]),
        "deltas_vs_design": {
            "pooled": delta_block(pooled, ref_tt["pooled"]),
            "per_season": {
                str(s): delta_block(per_season[s],
                                    ref_tt["per_season"][str(s)])
                for s in TEST_SEASONS},
        },
        "note": ("Reproduction of a DESIGN screen on seen seasons; an "
                 "entry ticket, never validation. The implied split is "
                 "an untimestamped design diagnostic (gap G7), "
                 "reproduced only to carry the design's disclosure "
                 "forward verbatim."),
    }
    text = json.dumps(report, indent=1, default=float)
    with open(args.out, "w") as fh:
        fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
