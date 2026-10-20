"""Calibration SCREEN for the NFL prop engines v1
(sportsedge/nfl_prop_engines_v1.py).  RESEARCH_EVIDENCE only.

This is a SCREEN on USED data — the same 2020-2025 vintage the frozen
Part 2 calibration screen scored — not validation.  A CALIBRATED_
CANDIDATE here is an entry ticket to a forward test, exactly as in
Part 2; it confers no eligibility.  Each family's construction is
scored ONCE, as built; nothing is tuned against this screen.

Method (the Part 2 evaluator's, unchanged): per family, one pooled CV
from the training seasons (2018-2019) as the std/mean of outcome/mu
ratios over qualified rows; scored rows are qualified player-weeks
(week >= 4) of 2020-2025; CRPS of the candidate CDF vs B1 (the player's
own prior empirical CDF) and B2 (the qualified league-pool empirical
CDF); verdict CALIBRATED_CANDIDATE iff both block-bootstrap (season-
week blocks, seed 20261017, 2000 resamples) delta-CRPS 95% CIs lie
entirely below zero, else DOES_NOT_BEAT_BASELINE.

Kicking and defensive families (fg_made, xp_made, kicking_points,
player_sacks, tackles_assists, player_interceptions) have outcome
columns only in the sp_2025 file of the sanctioned snapshot — the
2020-2024 ps files carry no kicking or defensive columns at all — so
the mandated 2020-2025 screen CANNOT RUN for them.  Their verdict is
SCREEN_NOT_RUNNABLE_SANCTIONED_VINTAGE, and this script additionally
emits a fenced 2025-only point-in-time diagnostic (CV from qualified
rows of weeks <= 8, scored on weeks >= 9, same CRPS/bootstrap
machinery), labeled DIAGNOSTIC_PARTIAL_VINTAGE_2025_ONLY.  The
diagnostic is supplementary evidence about the construction, never
the family verdict.

Usage: python3 screen_nfl_prop_engines_v1.py --data DIR --out results.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sportsedge import nfl_prop_engines_v1 as eng  # noqa: E402

SEED, RESAMPLES = 20261017, 2000
TRAIN, SCORED = (2018, 2019), tuple(range(2020, 2026))
MAIN_FAMILIES = ("pass_plus_rush_yards", "rush_plus_rec_yards",
                 "targets", "two_plus_td")
PARTIAL_FAMILIES = ("fg_made", "xp_made", "kicking_points",
                    "player_sacks", "tackles_assists",
                    "player_interceptions")
DIAG_CV_MAX_WEEK, DIAG_SCORE_MIN_WEEK = 8, 9

GRID = np.arange(eng.GRID_LO, eng.GRID_HI + 1, dtype=float)


def crps(cdf, y):
    ind = (GRID >= y).astype(float)
    return float(np.sum((cdf - ind) ** 2))


def boot(vals, blocks):
    """The Part 2 evaluator's block bootstrap, unchanged."""
    vals = np.asarray(vals, float)
    keys = sorted(set(blocks))
    idx = {k: n for n, k in enumerate(keys)}
    bi = np.array([idx[b] for b in blocks])
    sums, cnts = np.zeros(len(keys)), np.zeros(len(keys))
    np.add.at(sums, bi, vals)
    np.add.at(cnts, bi, 1)
    rng = np.random.default_rng(SEED)
    s = rng.integers(0, len(keys), size=(RESAMPLES, len(keys)))
    m = sums[s].sum(1) / cnts[s].sum(1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return {"mean": float(vals.mean()), "ci95_lo": float(lo),
            "ci95_hi": float(hi), "n": int(len(vals)),
            "n_blocks": len(keys)}


def train_cv(seasons: dict, cfg: dict, train_seasons) -> float:
    ratios = []
    for s in train_seasons:
        for w, _, prior, y in seasons.get(s, []):
            pool = eng.league_pool(seasons, s, w)
            if not pool:
                continue
            ratios.append(y / max(eng.mu_for(prior, pool), 1e-6))
    ratios = np.asarray(ratios)
    return float(ratios.std() / ratios.mean()), int(len(ratios))


def score_rows(seasons: dict, cfg: dict, cv: float, scored_seasons,
               min_week: int) -> list:
    rows = []
    for s in scored_seasons:
        for w, pid, prior, y in seasons.get(s, []):
            if w < min_week:
                continue
            pool = eng.league_pool(seasons, s, w)
            if not pool:
                continue
            mu = eng.mu_for(prior, pool)
            c_c = eng.candidate_cdf(mu, cv, cfg["count"], GRID)
            line = float(np.floor(np.median(prior)) + 0.5)
            if cfg["count"]:
                p_over = 1.0 - float(c_c[int(line - 0.5) - eng.GRID_LO])
            else:
                p_over = 1.0 - float(np.interp(line, GRID, c_c))
            rows.append({
                "block": f"{s}-W{w:02d}", "season": s, "week": w,
                "pid": pid, "y": float(y), "mu": float(mu),
                "crps_c": crps(c_c, y),
                "crps_b1": crps(eng.emp_cdf(prior, GRID), y),
                "crps_b2": crps(eng.emp_cdf(pool, GRID), y),
                "p_over_line": p_over, "over": float(y > line),
                "pit": float(np.interp(y, GRID, c_c))})
    return rows


def summarize(rows: list) -> dict:
    blocks = [r["block"] for r in rows]
    res = {"n": len(rows),
           "crps": {a: float(np.mean([r[k] for r in rows]))
                    for a, k in (("CANDIDATE", "crps_c"), ("B1", "crps_b1"),
                                 ("B2", "crps_b2"))},
           "delta_vs_B1": boot([r["crps_c"] - r["crps_b1"] for r in rows],
                               blocks),
           "delta_vs_B2": boot([r["crps_c"] - r["crps_b2"] for r in rows],
                               blocks)}
    res["beats_both"] = bool(res["delta_vs_B1"]["ci95_hi"] < 0
                             and res["delta_vs_B2"]["ci95_hi"] < 0)
    res["pit_hist"] = np.histogram([r["pit"] for r in rows], bins=10,
                                   range=(0, 1))[0].tolist()
    order = sorted(rows, key=lambda r: r["p_over_line"])
    res["over_line_deciles"] = [
        {"mean_p_over": float(np.mean([r["p_over_line"] for r in part])),
         "realized_over": float(np.mean([r["over"] for r in part])),
         "n": len(part)}
        for part in (order[k * len(order) // 10:(k + 1) * len(order) // 10]
                     for k in range(10))]
    return res


def screen_main_family(data: dict, name: str) -> dict:
    cfg = eng.FAMILIES[name]
    seasons = eng.build(data, cfg)
    cv, n_ratios = train_cv(seasons, cfg, TRAIN)
    rows = score_rows(seasons, cfg, cv, SCORED, min_week=4)
    res = summarize(rows)
    return {"family": name, "market": cfg["market"], "stat": cfg["stat"],
            "role": cfg["role"], "thr": cfg["thr"], "count": cfg["count"],
            "screen_vintage": "2020-2025",
            "cv": cv, "cv_source": "TRAIN_2018_2019_POOLED_RATIO",
            "n_train_ratios": n_ratios,
            "verdict": "CALIBRATED_CANDIDATE" if res.pop("beats_both")
                       else "DOES_NOT_BEAT_BASELINE",
            **res}


def diagnostic_2025(data: dict, name: str) -> dict:
    cfg = eng.FAMILIES[name]
    view = {2025: data.get(2025, {})}
    seasons = eng.build(view, cfg)
    ratios = []
    for w, _, prior, y in seasons.get(2025, []):
        if w > DIAG_CV_MAX_WEEK:
            continue
        pool = eng.league_pool(seasons, 2025, w)
        if not pool:
            continue
        ratios.append(y / max(eng.mu_for(prior, pool), 1e-6))
    ratios = np.asarray(ratios)
    cv = float(ratios.std() / ratios.mean()) if len(ratios) else None
    out = {"family": name, "market": cfg["market"], "stat": cfg["stat"],
           "role": cfg["role"], "thr": cfg["thr"], "count": cfg["count"],
           "screen_vintage": "NOT_RUNNABLE",
           "verdict": "SCREEN_NOT_RUNNABLE_SANCTIONED_VINTAGE",
           "verdict_reason": "kicking/defensive outcome columns exist "
                             "only in sp_2025; the ps files for "
                             "2020-2024 carry no such columns, so the "
                             "2020-2025 screen has no outcomes to score",
           "diagnostic": None}
    if cv is not None:
        rows = score_rows(seasons, cfg, cv, (2025,),
                          min_week=DIAG_SCORE_MIN_WEEK)
        if rows:
            res = summarize(rows)
            beats = res.pop("beats_both")
            out["diagnostic"] = {
                "label": "DIAGNOSTIC_PARTIAL_VINTAGE_2025_ONLY",
                "cv": cv,
                "cv_source": "2025_WEEKS_LE_8_POOLED_RATIO",
                "n_train_ratios": int(len(ratios)),
                "scored_weeks": f">= {DIAG_SCORE_MIN_WEEK}",
                "diagnostic_beats_both_baselines": beats, **res}
            out["cv_from_diagnostic"] = cv
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    hashes = {}
    for p in sorted(a.data.glob("*.csv.gz")) + [a.data / "games.csv"]:
        if p.exists():
            hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    data = eng.load_player_data(a.data)
    results = {"label": "SCREEN — calibration screen on USED data "
                        "(2020-2025 vintage, as the Part 2 screen). "
                        "An entry ticket, not validation.",
               "data_dir": str(a.data), "data_sha256": hashes,
               "K": eng.K, "seed": SEED, "resamples": RESAMPLES,
               "families": {}, "not_built": {}, "already_engined": {}}
    for name in MAIN_FAMILIES:
        r = screen_main_family(data, name)
        results["families"][name] = r
        print(name, r["verdict"], "n=", r["n"], "cv=", round(r["cv"], 4),
              "CRPS", {k: round(v, 3) for k, v in r["crps"].items()},
              "dB2", [round(r["delta_vs_B2"][k], 4)
                      for k in ("mean", "ci95_lo", "ci95_hi")])
    for name in PARTIAL_FAMILIES:
        r = diagnostic_2025(data, name)
        results["families"][name] = r
        d = r["diagnostic"]
        print(name, r["verdict"],
              ("diag n=" + str(d["n"]) + " cv=" + str(round(d["cv"], 4))
               + " beats_both=" + str(d["diagnostic_beats_both_baselines"]))
              if d else "diag=None")
    for name in ("longest_completion", "longest_rush", "longest_reception"):
        results["not_built"][name] = {
            "verdict": "ENGINE_NOT_BUILT_NO_OUTCOME_DATA_IN_SANCTIONED_SNAPSHOT",
            "reason": "no per-game longest-play outcome exists in any "
                      "sanctioned snapshot file (game logs carry sums "
                      "and counts, never a max); a game-log engine "
                      "would have to fabricate its outcome. An in-repo "
                      "play-by-play research engine "
                      "(nfl_longest_plays_empirical) exists but sits "
                      "outside this build's data mandate and remains "
                      "governance-unadmitted."}
    results["not_built"]["interceptions"] = {
        "verdict": "NOT_BUILT_SCOPE_RULED",
        "reason": "owner ruling: interceptions are OUT of the Part 2B "
                  "scope; the pricer refuses MARKET_OUT_OF_SCOPE_2B."}
    results["not_built"]["first_td"] = {
        "verdict": "NOT_BUILT_RESOLVES_NO_DATA_NOT_NO_ENGINE",
        "reason": "canonical coverage resolves first_td NO_DATA "
                  "(NO_VERIFIED_FIRST_SCORING_ATTRIBUTION); the gap "
                  "is first-scoring attribution data, not an engine."}
    results["already_engined"] = {
        "passing_yards": "Part 2 frozen evaluator (main)",
        "rushing_yards": "Part 2 frozen evaluator (main)",
        "rush_yards": "alias of rushing_yards — Part 2 frozen evaluator",
        "receiving_yards": "Part 2 frozen evaluator (main)",
        "receptions": "Part 2 frozen evaluator (main)",
        "rush_attempts": "Part 2B (PR #2415)",
        "attempts": "Part 2B (PR #2415)",
        "completions": "Part 2B (PR #2415)",
        "passing_tds": "Part 2B shadow (PR #2415)",
        "anytime_td": "engine v1, branch feat/nfl-atd-engine-v1-20261018",
    }
    a.out.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
