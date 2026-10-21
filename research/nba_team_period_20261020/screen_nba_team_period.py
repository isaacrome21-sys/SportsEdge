"""Single screen of the NBA team-total / period engine
(sportsedge/nba_team_period_engine.py) on the sanctioned vintage: the
public SBR archive nba_archive_10Y.json (sha256 pinned below), exactly
the data and protocol of specs/SPEC_NBA_GAME_LEVEL_V1.md (Oct 18
backtest-everything sweep).

Two forms REPRODUCE the published sweep through the engine:
  TEAM_TOTAL        (sweep B4,  n=15,506 target)
  TEAM_QUARTER_TOTAL(sweep B11, n=62,024 target)
Three forms are scored here for the FIRST time as exact mechanical
aggregations of the same two primitives (half share = sum of its
quarter shares; game period total = home + away team period totals),
labeled FIRST_SCREEN_AGGREGATION — they are not reproductions and no
published figure exists for them:
  GAME_QUARTER_TOTAL, TEAM_HALF_TOTAL, GAME_HALF_TOTAL

Baselines (the spec's climatology pair, expanding in-season, priors
only): B1 = team's expanding in-season mean of the same quantity;
B2 = league expanding in-season mean of the same quantity (for game
forms, B1 = the two teams' means summed and B2 = 2x the league mean —
the spec's per-team baseline idiom aggregated). Metric: MAE primary,
RMSE secondary. Inference: paired ISO-week block bootstrap over game
dates, 2,000 resamples, seed 20261018 (the spec's machinery, copied).
Verdict per form: paired 95% CI for (candidate - baseline) MAE
entirely below zero vs BOTH baselines -> CALIBRATED_CANDIDATE (the
program label for the spec's calibration-class BEATS_BASELINE), else
DOES_NOT_BEAT_BASELINE. CALIBRATION ONLY — no market leg exists for
these families and none is claimed.

Run once. Do not tune the construction against this screen.
"""
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import date

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sportsedge.nba_team_period_engine import NBATeamPeriodEngine  # noqa: E402

ARCHIVE = os.path.expanduser(
    "~/workspace/sportsedge/nba_totals_bias_20261018/data/nba_archive_10Y.json")
ARCHIVE_SHA256 = ("0c9858489d224c54dcf2f2d1b70c3a122675381d35ae03ce0a81204f739f0e98")
SPEC = os.path.expanduser(
    "~/workspace/sportsedge/backtest_everything_20261018/specs/SPEC_NBA_GAME_LEVEL_V1.md")
PUBLISHED = os.path.expanduser(
    "~/workspace/sportsedge/backtest_everything_20261018/results/nba_game_level_results.json")
OUT = os.path.join(os.path.dirname(__file__), "screen_results_v1.json")
SCORE_SEASONS = set(range(2015, 2022))
BOOT_N = 2000
SEED = 20261018


def parse_games():
    """Identical parsing to the Oct 18 scorer (same fields, same
    exclusion counting)."""
    with open(ARCHIVE) as f:
        raw = json.load(f)
    games, bad = [], 0
    for i, r in enumerate(raw):
        try:
            dnum = int(float(r["date"]))
            d = date(dnum // 10000, (dnum // 100) % 100, dnum % 100)
            hp = float(r["home_final"])
            ap = float(r["away_final"])
            hq = tuple(int(float(r[f"home_{q}Qtr"]))
                       for q in ("1st", "2nd", "3rd", "4th"))
            aq = tuple(int(float(r[f"away_{q}Qtr"]))
                       for q in ("1st", "2nd", "3rd", "4th"))
            season = int(r["season"])
        except (KeyError, TypeError, ValueError):
            bad += 1
            continue
        games.append({"game_id": f"{d.isoformat()}-{i}", "idx": i,
                      "season": season, "date": d.isoformat(), "_d": d,
                      "home": str(r["home_team"]), "away": str(r["away_team"]),
                      "home_pts": hp, "away_pts": ap, "hq": hq, "aq": aq})
    return games, bad, len(raw)


def block_ci(rows, d_cand_b1, d_cand_b2):
    """The spec's paired ISO-week block bootstrap, verbatim form."""
    rng = np.random.default_rng(SEED)
    blocks = defaultdict(lambda: [0.0, 0.0, 0])
    for r, a1, a2 in zip(rows, d_cand_b1, d_cand_b2):
        iso = r["_d"].isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        blocks[key][0] += a1
        blocks[key][1] += a2
        blocks[key][2] += 1
    keys = sorted(blocks)
    bs = np.array([blocks[k][0] for k in keys])
    bs2 = np.array([blocks[k][1] for k in keys])
    bc = np.array([blocks[k][2] for k in keys], dtype=float)
    nb = len(keys)
    idx = rng.integers(0, nb, size=(BOOT_N, nb))
    m1 = bs[idx].sum(axis=1) / bc[idx].sum(axis=1)
    m2 = bs2[idx].sum(axis=1) / bc[idx].sum(axis=1)
    return ([float(np.percentile(m1, 2.5)), float(np.percentile(m1, 97.5))],
            [float(np.percentile(m2, 2.5)), float(np.percentile(m2, 97.5))], nb)


def summarize(rows):
    mae = {k: float(np.mean([r[f"ae_{k}"] for r in rows])) for k in ("c", "1", "2")}
    rmse = {k: float(np.sqrt(np.mean([r[f"se_{k}"] for r in rows])))
            for k in ("c", "1", "2")}
    d1 = np.array([r["ae_c"] - r["ae_1"] for r in rows])
    d2 = np.array([r["ae_c"] - r["ae_2"] for r in rows])
    ci1, ci2, nb = block_ci(rows, d1, d2)
    return {"n": len(rows), "mae_candidate": mae["c"],
            "mae_b1_team_mean": mae["1"], "mae_b2_league_mean": mae["2"],
            "rmse_candidate": rmse["c"], "rmse_b1_team_mean": rmse["1"],
            "rmse_b2_league_mean": rmse["2"],
            "paired_delta_mae_vs_b1": float(np.mean(d1)), "ci95_vs_b1": ci1,
            "paired_delta_mae_vs_b2": float(np.mean(d2)), "ci95_vs_b2": ci2,
            "blocks_iso_weeks": nb,
            "verdict": "CALIBRATED_CANDIDATE" if (ci1[1] < 0 and ci2[1] < 0)
                       else "DOES_NOT_BEAT_BASELINE"}


def row(_d, pred, b1, b2, actual, **extra):
    r = {"_d": _d, "ae_c": abs(pred - actual), "ae_1": abs(b1 - actual),
         "ae_2": abs(b2 - actual), "se_c": (pred - actual) ** 2,
         "se_1": (b1 - actual) ** 2, "se_2": (b2 - actual) ** 2}
    r.update(extra)
    return r


def main():
    with open(ARCHIVE, "rb") as f:
        archive_sha = hashlib.sha256(f.read()).hexdigest()
    if archive_sha != ARCHIVE_SHA256:
        raise SystemExit(f"archive hash mismatch: {archive_sha}")
    with open(SPEC, "rb") as f:
        spec_sha = hashlib.sha256(f.read()).hexdigest()

    games, bad, total_rows = parse_games()
    games = [{**g, "home_quarters": g["hq"], "away_quarters": g["aq"]}
             for g in games]
    eng = NBATeamPeriodEngine()
    fit = eng.fit_periods(games, source="sbr_archive_10Y",
                          source_version="clone_20261018")

    forms = {"TEAM_TOTAL": [], "TEAM_QUARTER_TOTAL": [],
             "GAME_QUARTER_TOTAL": [], "TEAM_HALF_TOTAL": [],
             "GAME_HALF_TOTAL": []}
    for g in sorted(games, key=lambda x: (x["date"], str(x["home"]))):
        fc = eng.forecast(g["home"], g["away"], season=g["season"],
                          target_date=g["date"])
        if g["season"] in SCORE_SEASONS and fc["status"] == "PRICED":
            bl, per = fc["baselines"], fc["periods"]
            sides = (("home", g["home_pts"], g["hq"]),
                     ("away", g["away_pts"], g["aq"]))
            for side, pts, qs in sides:
                forms["TEAM_TOTAL"].append(row(
                    g["_d"], fc["team_totals"][side],
                    bl[f"{side}_team_mean"], bl["league_mean"], pts))
                for q in range(4):
                    forms["TEAM_QUARTER_TOTAL"].append(row(
                        g["_d"], per["team_quarter_totals"][side][q],
                        bl[f"{side}_quarter_means"][q],
                        bl["league_quarter_means"][q], qs[q], quarter=q + 1))
                for h in range(2):
                    forms["TEAM_HALF_TOTAL"].append(row(
                        g["_d"], per["team_half_totals"][side][h],
                        bl[f"{side}_half_means"][h],
                        bl["league_half_means"][h],
                        qs[2 * h] + qs[2 * h + 1]))
            for q in range(4):
                forms["GAME_QUARTER_TOTAL"].append(row(
                    g["_d"], per["game_quarter_totals"][q],
                    bl["home_quarter_means"][q] + bl["away_quarter_means"][q],
                    2 * bl["league_quarter_means"][q],
                    g["hq"][q] + g["aq"][q]))
            for h in range(2):
                forms["GAME_HALF_TOTAL"].append(row(
                    g["_d"], per["game_half_totals"][h],
                    bl["home_half_means"][h] + bl["away_half_means"][h],
                    2 * bl["league_half_means"][h],
                    sum(g["hq"][2 * h:2 * h + 2]) + sum(g["aq"][2 * h:2 * h + 2])))
        eng.consume(g)

    out = {"kind": "CALIBRATION_ONLY_NO_MARKET_LEG",
           "evidence_label": "SCREEN_20261020",
           "spec_sha256": spec_sha, "archive_sha256": archive_sha,
           "archive_rows_total": total_rows,
           "archive_rows_unparseable": bad,
           "archive_games_used": len(games),
           "period_fit": {"version": fit.version,
                          "quarter_shares": list(fit.quarter_shares),
                          "fit_span": "seasons<=2014"},
           "ratings_params": "NBARatingsParams committed defaults",
           "score_seasons": sorted(SCORE_SEASONS)}
    provenance = {"TEAM_TOTAL": "REPRODUCTION_OF_OCT18_B4",
                  "TEAM_QUARTER_TOTAL": "REPRODUCTION_OF_OCT18_B11",
                  "GAME_QUARTER_TOTAL": "FIRST_SCREEN_AGGREGATION",
                  "TEAM_HALF_TOTAL": "FIRST_SCREEN_AGGREGATION",
                  "GAME_HALF_TOTAL": "FIRST_SCREEN_AGGREGATION"}
    for name, rows_ in forms.items():
        s = summarize(rows_)
        s["provenance"] = provenance[name]
        out[name] = s
    # per-quarter descriptive table for TEAM_QUARTER_TOTAL (as published)
    per_q = {}
    for q in (1, 2, 3, 4):
        sub = [r for r in forms["TEAM_QUARTER_TOTAL"] if r["quarter"] == q]
        per_q[str(q)] = {
            "n": len(sub),
            "mae_candidate": float(np.mean([r["ae_c"] for r in sub])),
            "mae_b1": float(np.mean([r["ae_1"] for r in sub])),
            "mae_b2": float(np.mean([r["ae_2"] for r in sub]))}
    out["TEAM_QUARTER_TOTAL"]["per_quarter_mae"] = per_q

    with open(PUBLISHED) as f:
        pub = json.load(f)
    parity = {}
    for mine, theirs in (("TEAM_TOTAL", "B4_team_totals"),
                         ("TEAM_QUARTER_TOTAL", "B11_quarter_totals")):
        diffs = {}
        for k in ("n", "mae_candidate", "mae_b1_team_mean",
                  "mae_b2_league_mean", "rmse_candidate",
                  "paired_delta_mae_vs_b1", "paired_delta_mae_vs_b2",
                  "blocks_iso_weeks"):
            diffs[k] = abs(out[mine][k] - pub[theirs][k])
        for k in ("ci95_vs_b1", "ci95_vs_b2"):
            diffs[k] = max(abs(a - b) for a, b in
                           zip(out[mine][k], pub[theirs][k]))
        parity[mine] = {"max_abs_diff": max(diffs.values()), "diffs": diffs}
    parity["period_fit_version"] = {
        "mine": fit.version, "published": pub["period_fit"]["version"],
        "match": fit.version == pub["period_fit"]["version"]}
    parity["quarter_shares_max_abs_diff"] = max(
        abs(a - b) for a, b in zip(fit.quarter_shares,
                                   pub["period_fit"]["quarter_shares"]))
    pq_diffs = {}
    for q in ("1", "2", "3", "4"):
        for k in ("n", "mae_candidate", "mae_b1", "mae_b2"):
            pq_diffs[f"q{q}_{k}"] = abs(
                out["TEAM_QUARTER_TOTAL"]["per_quarter_mae"][q][k]
                - pub["B11_quarter_totals"]["per_quarter_mae"][q][k])
    parity["per_quarter_mae_max_abs_diff"] = max(pq_diffs.values())
    out["parity_vs_oct18_published"] = parity

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
