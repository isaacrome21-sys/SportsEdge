"""M49 plate-appearance engine screen — run ONCE, on the sanctioned
vintage the M49 record used (the 2025 pool), scoring THROUGH the
engine module (sportsedge.mlb_plate_appearance_engine).

Label: RESEARCH_EVIDENCE — retrospective calibration screen of the
engine build against the frozen M49 construction (SPEC_M49_PA.md,
sha256 2e2cb70d69607f9320dc9b6cd3b19e1fd71c98c4281515affe93e81eede3f84f).
NOT a market verdict, NOT validation, NOT a promotion input.  The
construction was scored once by the Oct 17 program (BEATS_BASELINE);
this screen runs the engine's own code path over the same vintage
and reports (a) parity with that record and (b) per-family verdicts
in the program's screen labels (CALIBRATED_CANDIDATE /
DOES_NOT_BEAT_BASELINE / NO_DATA):

* PLATE_APPEARANCE_RESULT — the 1st-PA subset, six-category paired
  log score vs both baselines (the spec's section-4 readout (ii)).
* PLATE_APPEARANCE_ON_BASE — the 1st-PA subset, binary reached log
  score vs both baselines, using the spec's section-4 paired
  block-bootstrap machinery on the binary the spec declared
  descriptively (reached := category in {BB_HBP, SINGLE, XBH, HR}).
* PLATE_APPEARANCE_GROUPED_RESULT — NO_DATA.  DraftKings' exact
  3-way partition is unverified (PLATE_APPEARANCE_SELECTION_SET_
  UNVERIFIED); no partition is invented here, so no grouped score
  exists to report.  The priced object is the six-category
  distribution; any verified partition is a coarsening of it.

The walk mirrors eval_m49_pa.py exactly (same feeding order, same
eligibility accounting, same scoring floor, same bootstrap — copied
verbatim below with attribution), except that every candidate
distribution comes from the engine's shrunk_distribution, and the
engine's pool index path is asserted equal to the walk counters on
a deterministic sample of batter-games.  No parameter was tuned:
k = 50 and the 50-PA gate are the spec's, read from the engine.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))
from sportsedge.mlb_plate_appearance_engine import (  # noqa: E402
    CATEGORIES, K_SHRINK, MIN_PRIOR_PA, REACHED_CATEGORIES, SPEC_SHA256,
    PlateAppearancePool, category_of, load_pool_rows, shrunk_distribution)

POOL_DIR = os.environ.get(
    "SPORTSEDGE_MLB_PBP_POOL_DIR",
    os.path.expanduser("~/workspace/sportsedge/mlb_pbp_pool_20261016"))
POOL_2025_GZ_SHA256 = \
    "699ac96ad44d0534bf054460990a567aa30f69d9875762899b386ef15a059120"
SPEC_PATH = os.environ.get(
    "SPORTSEDGE_M49_SPEC",
    os.path.expanduser(
        "~/workspace/sportsedge/backtest_program_20261017/lanes/mlb/"
        "specs/SPEC_M49_PA.md"))
RECORD_PATH = os.environ.get(
    "SPORTSEDGE_M49_RECORD",
    os.path.expanduser(
        "~/workspace/sportsedge/backtest_program_20261017/lanes/mlb/"
        "results/mlb_m49_pa_results.json"))
SEASON = 2025
SEED = 20261017
EPS = 1e-6
SPOT_CHECK_EVERY = 613


# ---- copied verbatim from eval_m49_pa.py (Oct 17 program), except
# ---- the default seed is written literally; attribution above.
def floored(probs):
    p = np.maximum(np.asarray(probs, dtype=np.float64), EPS)
    return p / p.sum()


def block_bootstrap_ci(diffs_by_week, n_boot=2000, seed=SEED):
    weeks = sorted(diffs_by_week)
    sums = np.array([diffs_by_week[w][0] for w in weeks], dtype=np.float64)
    counts = np.array([diffs_by_week[w][1] for w in weeks], dtype=np.float64)
    point = sums.sum() / counts.sum()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(weeks), size=(n_boot, len(weeks)))
    boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def paired(recs, ek, bk):
    by_week = defaultdict(lambda: [0.0, 0])
    for r in recs:
        by_week[r["week"]][0] += r[ek] - r[bk]
        by_week[r["week"]][1] += 1
    return block_bootstrap_ci({w: tuple(v) for w, v in by_week.items()})


def summarize(recs, cand_key, league_key, raw_key):
    out = {"n_pa": len(recs)}
    for arm, k in (("candidate", cand_key), ("league", league_key),
                   ("raw_empirical", raw_key)):
        out[f"mean_logloss_{arm}"] = float(np.mean([r[k] for r in recs]))
    for label, ek, bk in (("dLogLoss_vs_league", cand_key, league_key),
                          ("dLogLoss_vs_raw", cand_key, raw_key)):
        pt, lo, hi = paired(recs, ek, bk)
        out[label] = {"delta": pt, "ci95": [lo, hi],
                      "entirely_below_zero": bool(hi < 0)}
    out["beats_both_baselines"] = bool(
        out["dLogLoss_vs_league"]["entirely_below_zero"]
        and out["dLogLoss_vs_raw"]["entirely_below_zero"])
    return out


def screen_label(summary):
    return "CALIBRATED_CANDIDATE" if summary["beats_both_baselines"] \
        else "DOES_NOT_BEAT_BASELINE"


def main():
    # ---- pins verified before any scoring (fail closed) ----
    spec_verified = False
    if os.path.exists(SPEC_PATH):
        h = hashlib.sha256(open(SPEC_PATH, "rb").read()).hexdigest()
        assert h == SPEC_SHA256, f"SPEC HASH MISMATCH {h}"
        spec_verified = True
    pool_path = os.path.join(POOL_DIR, f"pool_{SEASON}.jsonl.gz")
    gz_hash = hashlib.sha256(open(pool_path, "rb").read()).hexdigest()
    assert gz_hash == POOL_2025_GZ_SHA256, f"POOL HASH MISMATCH {gz_hash}"
    manifest = json.load(open(os.path.join(POOL_DIR, "MANIFEST.json")))
    assert manifest["seasons"][str(SEASON)]["sha256_gz"] == gz_hash

    # ---- load through the engine (validation + pool index) ----
    pool_rows = load_pool_rows([pool_path])
    pool = PlateAppearancePool(pool_rows)
    assert pool.seasons == {SEASON}

    # ---- the walk: games grouped exactly as eval_m49_pa.py ----
    games = {}
    outcome_counts = Counter()
    with gzip.open(pool_path, "rt") as f:
        for line in f:
            o = json.loads(line)
            outcome_counts[o["outcome_class"]] += 1
            cat = category_of(o["outcome_class"])
            g = games.get(o["game_id"])
            if g is None:
                g = games[o["game_id"]] = {
                    "date": o["game_date"],
                    "completed": o["game_completed_date"], "pas": []}
            g["pas"].append((o["batter_id"], o["batter_pa_number"], cat))
    by_completed = defaultdict(list)
    for gid, g in games.items():
        by_completed[g["completed"]].append(gid)
    targets_by_date = defaultdict(list)
    for gid, g in games.items():
        targets_by_date[g["date"]].append(gid)
    target_dates = sorted(targets_by_date)

    batter_counts = defaultdict(Counter)
    batter_n = Counter()
    league_counts = Counter()
    league_n = 0
    fed_completed = set()
    records = []
    elig_bg = 0
    inelig_bg = Counter()
    total_bg = 0
    spot_checks = 0
    bg_counter = 0

    for d in target_dates:
        for cd in sorted(c for c in by_completed
                         if c < d and c not in fed_completed):
            for gid in by_completed[cd]:
                for batter, _pa_no, cat in games[gid]["pas"]:
                    batter_counts[batter][cat] += 1
                    batter_n[batter] += 1
                    league_counts[cat] += 1
                    league_n += 1
            fed_completed.add(cd)
        if league_n == 0:
            continue
        league_tuple = tuple(league_counts[c] for c in CATEGORIES)
        p_league = np.array([league_counts[c] / league_n
                             for c in CATEGORIES])
        for gid in targets_by_date[d]:
            g = games[gid]
            batters = {b for b, _n, _c in g["pas"]}
            elig = {}
            for b in batters:
                total_bg += 1
                if batter_n[b] >= MIN_PRIOR_PA:
                    elig[b] = True
                else:
                    inelig_bg[d[:7]] += 1
            if not elig:
                continue
            dists = {}
            for b in elig:
                bg_counter += 1
                b_tuple = tuple(batter_counts[b][c] for c in CATEGORIES)
                if bg_counter % SPOT_CHECK_EVERY == 0:
                    # the engine's indexed pool path must reproduce
                    # the walk counters exactly, or the screen stops
                    assert pool.batter_prior_counts(b, SEASON, d) == b_tuple
                    assert pool.league_prior_counts(SEASON, d) == league_tuple
                    spot_checks += 1
                nb = batter_n[b]
                emp = np.array([batter_counts[b][c] / nb
                                for c in CATEGORIES])
                cand = np.array(shrunk_distribution(b_tuple, league_tuple))
                dists[b] = (floored(cand), floored(p_league), floored(emp))
            wk = date.fromisoformat(d).isocalendar()
            week = f"{wk[0]}-W{wk[1]:02d}"
            seen_bg = set()
            for batter, pa_no, cat in g["pas"]:
                if batter not in dists:
                    continue
                if batter not in seen_bg:
                    seen_bg.add(batter)
                    elig_bg += 1
                ci = CATEGORIES.index(cat)
                pc, pl, pr = dists[batter]
                reached = 1 if cat in REACHED_CATEGORIES else 0
                ridx = [CATEGORIES.index(c) for c in
                        sorted(REACHED_CATEGORIES,
                               key=CATEGORIES.index)]
                rc = float(pc[ridx].sum())
                rl = float(pl[ridx].sum())
                rr = float(pr[ridx].sum())
                records.append({
                    "week": week, "month": d[:7], "cat": cat,
                    "first_pa": pa_no == 1,
                    "ll_cand": -math.log(pc[ci]),
                    "ll_league": -math.log(pl[ci]),
                    "ll_raw": -math.log(pr[ci]),
                    "bll_cand": -(reached * math.log(rc)
                                  + (1 - reached) * math.log(1 - rc)),
                    "bll_league": -(reached * math.log(rl)
                                    + (1 - reached) * math.log(1 - rl)),
                    "bll_raw": -(reached * math.log(rr)
                               + (1 - reached) * math.log(1 - rr)),
                    "brier_cand": (rc - reached) ** 2,
                    "brier_league": (rl - reached) ** 2,
                    "p_cand_cat": float(pc[ci]),
                })
    print(f"scored PAs={len(records)} eligible batter-games={elig_bg} "
          f"total batter-games seen={total_bg} spot_checks={spot_checks}",
          flush=True)

    primary = summarize(records, "ll_cand", "ll_league", "ll_raw")
    first_pa = [r for r in records if r["first_pa"]]
    result_family = summarize(first_pa, "ll_cand", "ll_league", "ll_raw")
    onbase_family = summarize(first_pa, "bll_cand", "bll_league", "bll_raw")

    binary_all = {"n_pa": len(records)}
    for arm, k in (("candidate", "bll_cand"), ("league", "bll_league"),
                   ("raw_empirical", "bll_raw")):
        binary_all[f"mean_binary_logloss_{arm}"] = float(
            np.mean([r[k] for r in records]))
    binary_all["mean_brier_candidate"] = float(
        np.mean([r["brier_cand"] for r in records]))
    binary_all["mean_brier_league"] = float(
        np.mean([r["brier_league"] for r in records]))

    calib = {}
    for c in CATEGORIES:
        calib[c] = {
            "realized_share": float(np.mean(
                [1.0 if r["cat"] == c else 0.0 for r in records])),
            "mean_p_cand_on_category_rows": float(np.mean(
                [r["p_cand_cat"] for r in records if r["cat"] == c])),
        }

    # ---- parity with the Oct 17 record ----
    parity = {"record_path": RECORD_PATH, "compared": False}
    if os.path.exists(RECORD_PATH):
        rec = json.load(open(RECORD_PATH))
        parity["compared"] = True
        checks = {}

        def cmp(name, mine, theirs):
            checks[name] = {"screen": mine, "record": theirs,
                            "abs_diff": abs(mine - theirs)}

        cmp("primary.mean_logloss_candidate",
            primary["mean_logloss_candidate"],
            rec["primary_six_category_log_score"]["mean_logloss_candidate"])
        cmp("primary.dLogLoss_vs_league.delta",
            primary["dLogLoss_vs_league"]["delta"],
            rec["primary_six_category_log_score"]["dLogLoss_vs_league"]["delta"])
        cmp("primary.dLogLoss_vs_league.ci95_lo",
            primary["dLogLoss_vs_league"]["ci95"][0],
            rec["primary_six_category_log_score"]["dLogLoss_vs_league"]["ci95"][0])
        cmp("primary.dLogLoss_vs_league.ci95_hi",
            primary["dLogLoss_vs_league"]["ci95"][1],
            rec["primary_six_category_log_score"]["dLogLoss_vs_league"]["ci95"][1])
        cmp("primary.dLogLoss_vs_raw.delta",
            primary["dLogLoss_vs_raw"]["delta"],
            rec["primary_six_category_log_score"]["dLogLoss_vs_raw"]["delta"])
        cmp("first_pa.dLogLoss_vs_league.delta",
            result_family["dLogLoss_vs_league"]["delta"],
            rec["first_pa_subset_descriptive"]["dLogLoss_vs_league"]["delta"])
        cmp("first_pa.dLogLoss_vs_raw.delta",
            result_family["dLogLoss_vs_raw"]["delta"],
            rec["first_pa_subset_descriptive"]["dLogLoss_vs_raw"]["delta"])
        cmp("binary_all.mean_binary_logloss_candidate",
            binary_all["mean_binary_logloss_candidate"],
            rec["binary_reached_descriptive"]["mean_binary_logloss_candidate"])
        parity["figures"] = checks
        parity["max_abs_diff"] = max(
            v["abs_diff"] for v in checks.values())
        parity["population"] = {
            "batter_games_seen": total_bg,
            "record_batter_games_seen":
                rec["population"]["batter_games_seen"],
            "eligible_batter_games": elig_bg,
            "record_eligible_batter_games":
                rec["population"]["eligible_batter_games"],
            "scored_pas": len(records),
            "record_scored_pas": rec["population"]["scored_pas"],
            "first_pa_scored": len(first_pa),
            "record_first_pa_scored": rec["population"]["first_pa_scored"],
            "ineligible_by_month": dict(sorted(inelig_bg.items())),
            "record_ineligible_by_month":
                rec["population"]["ineligible_batter_games_by_month"],
        }
        parity["population_exact"] = (
            parity["population"]["batter_games_seen"]
            == parity["population"]["record_batter_games_seen"]
            and parity["population"]["eligible_batter_games"]
            == parity["population"]["record_eligible_batter_games"]
            and parity["population"]["scored_pas"]
            == parity["population"]["record_scored_pas"]
            and parity["population"]["first_pa_scored"]
            == parity["population"]["record_first_pa_scored"]
            and parity["population"]["ineligible_by_month"]
            == parity["population"]["record_ineligible_by_month"])
        print(f"parity max_abs_diff={parity['max_abs_diff']:.3e} "
              f"population_exact={parity['population_exact']}", flush=True)

    results = {
        "label": "RESEARCH_EVIDENCE — engine screen on the sanctioned "
                 "2025 vintage, scored through the engine's code path. "
                 "NOT a market verdict, NOT validation, NOT a "
                 "promotion input.",
        "evidence_state": "EXECUTED_20261020",
        "engine": "mlb_plate_appearance_engine_v1",
        "construction": "M49_PA_SHRUNK_EMPIRICAL_K50",
        "spec": {"sha256": SPEC_SHA256, "verified_on_disk": spec_verified},
        "data": {
            "pool_file": f"pool_{SEASON}.jsonl.gz",
            "pool_dir": POOL_DIR,
            "pool_sha256_gz": gz_hash,
            "manifest_pit_rule": manifest["pit_rule"],
            "rows": manifest["seasons"][str(SEASON)]["rows"],
            "games": manifest["seasons"][str(SEASON)]["games_admitted"],
            "outcome_class_counts": dict(outcome_counts),
            "source": manifest["source"],
        },
        "population": {
            "scoring_season": SEASON,
            "batter_games_seen": total_bg,
            "eligible_batter_games": elig_bg,
            "ineligible_batter_games_by_month": dict(sorted(inelig_bg.items())),
            "scored_pas": len(records),
            "first_pa_scored": len(first_pa),
            "engine_pool_spot_checks_passed": spot_checks,
        },
        "construction_primary_six_category": primary,
        "construction_verdict_record_label":
            "BEATS_BASELINE" if primary["beats_both_baselines"]
            else "DOES_NOT_BEAT_BASELINE",
        "families": {
            "PLATE_APPEARANCE_RESULT": {
                "population": "1st-PA subset (batter_pa_number == 1) of "
                              "eligible batter-games, same distributions",
                **result_family,
                "screen_verdict": screen_label(result_family),
            },
            "PLATE_APPEARANCE_ON_BASE": {
                "population": "1st-PA subset; binary reached := category "
                              "in {BB_HBP, SINGLE, XBH, HR} (spec section "
                              "4); paired bootstrap per the spec's "
                              "machinery",
                **onbase_family,
                "screen_verdict": screen_label(onbase_family),
                "all_pa_binary_descriptive": binary_all,
            },
            "PLATE_APPEARANCE_GROUPED_RESULT": {
                "screen_verdict": "NO_DATA",
                "reason": "PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED — "
                          "DraftKings' exact 3-way partition of PA "
                          "outcomes is not in the catalog evidence and "
                          "no partition is invented here; the engine "
                          "refuses this form (PLATE_APPEARANCE_GROUPED_"
                          "PARTITION_UNVERIFIED) until a partition is "
                          "verified, at which point it is a "
                          "deterministic coarsening of the priced "
                          "six-category distribution.",
            },
        },
        "candidate_category_calibration_descriptive": calib,
        "bootstrap": {"blocks": "ISO calendar weeks of game_date",
                      "resamples": 2000, "seed": SEED,
                      "ci": "95% percentile of block-bootstrap paired means"},
        "parity_with_oct17_record": parity,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "screen_results_v1.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=1)
    print("WROTE", out_path)
    print("primary verdict:",
          results["construction_verdict_record_label"])
    print("RESULT:", results["families"]["PLATE_APPEARANCE_RESULT"]
          ["screen_verdict"],
          json.dumps(result_family, indent=1))
    print("ON_BASE:", results["families"]["PLATE_APPEARANCE_ON_BASE"]
          ["screen_verdict"],
          json.dumps(onbase_family, indent=1))
    return results


if __name__ == "__main__":
    main()
