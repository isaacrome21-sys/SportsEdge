#!/usr/bin/env python3
"""RESEARCH_EVIDENCE — NFL totals LEVEL v2, Part A diagnostic screen.

(Derived from the LEVEL v1 evaluator; Stage 2 helpers kept verbatim.)

HARD LABELS (read before citing any number from this script):

* RETROSPECTIVE CALIBRATION on DEVELOPMENT data (2018–2025).
  NOT a market verdict, NOT validation, NOT a promotion input.
  Promotes NOTHING; changes no model, registry, card label, or
  threshold. The production NFL totals path keeps
  WATCH_NFL_TOTAL_PRIOR_ONLY whatever this run shows.
* Preregistration: PREREG_NFL_TOTALS_LEVEL_V2.md in this
  directory (SHA-256 locked in SPEC_HASHES.txt, verified at load;
  written before any candidate score was computed).
* Comparability: this evaluator REUSES the Stage 2 N3 evaluation
  (mlb_market_legs_20261014, spec SHA-256 9e005933...) — corpus,
  population, paired subset, CRPS constructions, and the ISO-week
  block bootstrap are copied from scripts/eval_nfl_calibration.py
  on research/mlb-market-legs-20261014 with attribution, and the
  reproduction precondition (prereg section 1) re-derives Stage
  2's frozen-prior and B2 numbers before any candidate verdict.
* The corpus file's line columns are never read.

Candidate: sportsedge/research/nfl_totals_level_v2.py
(preregistered construction; constants live in that module).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import importlib.util
import io
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sportsedge.research import nfl_totals_level_v2 as v2  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "free_models_pinned", REPO_ROOT / "artifacts" / "free_models.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261015
CLIM_MIN_PRIOR = 30
SEASONS = list(range(2018, 2026))
BURN_IN_SEASONS = [2017]
EXPECTED_DATASET_SHA256 = \
    "a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284"
EXPECTED_MODEL_BLOB = "253b0c6d91840c906941216be117f2acc1497a57"
TOTAL_BAND_GRID = [37.5, 40.5, 43.5, 46.5, 49.5, 52.5]
ET = ZoneInfo("America/New_York")
# Stage 2 published values — reproduction precondition (prereg §1).
STAGE2 = {"n_scored": 2127, "n_paired": 1887,
          "frozen_mean": 7.8225, "b2_mean": 7.7126,
          "delta": 0.1099, "ci_lo": 0.0283, "ci_hi": 0.1987}
REPRO_TOL = 1e-3


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_blob_id(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def verify_locks():
    locked = {}
    for line in (HERE / "SPEC_HASHES.txt").read_text().splitlines():
        line = line.strip()
        if line:
            digest, name = line.split(None, 1)
            locked[name.strip()] = digest
    prereg = HERE / "PREREG_NFL_TOTALS_LEVEL_V2.md"
    digest = sha256_of(prereg)
    if locked.get("PREREG_NFL_TOTALS_LEVEL_V2.md") != digest:
        raise SystemExit(
            f"PREREG_SHA256_MISMATCH: got {digest}, locked "
            f"{locked.get('PREREG_NFL_TOTALS_LEVEL_V2.md')} — "
            "refusing to score against an unlocked preregistration.")
    blob = git_blob_id(REPO_ROOT / "artifacts" / "free_models.py")
    if blob != EXPECTED_MODEL_BLOB:
        raise SystemExit(
            f"MODEL_BLOB_MISMATCH: got {blob}, expected "
            f"{EXPECTED_MODEL_BLOB} — the frozen prior is not the "
            "Stage 2 pin; refusing to score.")
    return digest


def derived_season(kickoff):
    """Production schedule() season rule (Stage 2 evaluator)."""
    return kickoff.year - 1 if kickoff.month <= 2 else kickoff.year


class CorpusProvider:
    """Stage 2 CorpusProvider, verbatim semantics: fixture =
    the corpus game; schedule = same-season completed games
    strictly before kickoff, descending, first 5; injury/weather
    are the declared neutralizations (0.0)."""

    def __init__(self, samples):
        self.samples = samples

    def fixture(self, sport, away, home, start):
        return start, "NFL"

    def identify(self, sport, name):
        return {"id": name, "name": name}

    def schedule(self, sport, team, kickoff):
        season = derived_season(kickoff)
        fid = team["id"]
        completed = [(k, pf, pa) for (k, s, pf, pa)
                     in self.samples.get(fid, [])
                     if k < kickoff and s == season]
        return sorted(completed, reverse=True)[:5]

    def injury_points(self, sport, team):
        return 0.0, "HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS"

    def weather(self, sport, competition, kickoff, latitude=None,
                longitude=None):
        return 0.0, "EVALUATION_NEUTRALIZED_NO_PIT_FORECAST"


def load_games(path):
    """Stage 2 load_games, verbatim semantics; only the manifested
    fields are accessed."""
    raw_bytes = Path(path).read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest != EXPECTED_DATASET_SHA256:
        raise SystemExit(
            f"DATASET_SHA256_MISMATCH: got {digest}, expected "
            f"{EXPECTED_DATASET_SHA256} — refusing to score a corpus "
            "that is not the manifested one.")
    games = []
    reg_by_season = Counter()
    total_rows = 0
    reader = csv.DictReader(io.StringIO(raw_bytes.decode("utf-8")))
    for row in reader:
        total_rows += 1
        if row["game_type"] != "REG":
            continue
        season = int(row["season"])
        if season not in SEASONS and season not in BURN_IN_SEASONS:
            continue
        if season in SEASONS:
            reg_by_season[season] += 1
        gametime = row["gametime"] or "00:00"
        kickoff = datetime.fromisoformat(
            f"{row['gameday']}T{gametime}").replace(tzinfo=ET)
        games.append({
            "kickoff": kickoff, "season": season,
            "away": row["away_team"], "home": row["home_team"],
            "away_score": (int(row["away_score"])
                           if row["away_score"] not in (None, "")
                           else None),
            "home_score": (int(row["home_score"])
                           if row["home_score"] not in (None, "")
                           else None),
        })
    games.sort(key=lambda g: (g["kickoff"], g["away"] or "",
                              g["home"] or ""))
    return games, total_rows, reg_by_season, digest


def block_bootstrap_ci(diffs_by_block, resamples=BOOTSTRAP_RESAMPLES,
                       seed=BOOTSTRAP_SEED):
    """Stage 2 block bootstrap, verbatim: ISO-week blocks, percentile
    95% CI of the mean paired difference."""
    blocks = [list(v) for v in diffs_by_block.values() if v]
    if not blocks:
        return None
    total_n = sum(len(b) for b in blocks)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        s, n = 0.0, 0
        for _ in range(len(blocks)):
            block = blocks[rng.randrange(len(blocks))]
            s += sum(block)
            n += len(block)
        means.append(s / n)
    means.sort()
    return {"mean_diff": sum(sum(b) for b in blocks) / total_n,
            "ci95_lo": means[int(0.025 * resamples)],
            "ci95_hi": means[min(resamples - 1,
                                 int(0.975 * resamples))],
            "n_blocks": len(blocks), "resamples": resamples}


def paired_summary(rows, model_key, base_key):
    out = {"n": len(rows)}
    if not rows:
        return out
    out[f"{model_key}_mean"] = sum(r[model_key] for r in rows) / len(rows)
    out[f"{base_key}_mean"] = sum(r[base_key] for r in rows) / len(rows)
    by_block = defaultdict(list)
    for r in rows:
        by_block[r["week"]].append(r[model_key] - r[base_key])
    out["paired_diff"] = block_bootstrap_ci(by_block)
    return out


def crps_normal(mean, sd, y):
    """Closed-form CRPS of Normal(mean, sd) at y (Stage 2)."""
    z = (y - mean) / sd
    phi = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    big_phi = fm.cdf(y, mean, sd)
    return sd * (z * (2.0 * big_phi - 1.0) + 2.0 * phi
                 - 1.0 / math.sqrt(math.pi))


def crps_empirical_int(pmf, y):
    """Integer-support empirical CRPS (Stage 2 construction)."""
    ks = sorted(pmf)
    lo, hi = ks[0], ks[-1]
    cum, idx, total = 0.0, 0, 0.0
    for k in range(lo - 1, hi + 1):
        while idx < len(ks) and ks[idx] <= k:
            cum += pmf[ks[idx]]
            idx += 1
        ind = 1.0 if y <= k else 0.0
        total += (cum - ind) ** 2
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--audit", default=None)
    args = ap.parse_args()

    prereg_digest = verify_locks()
    games_all, total_rows, reg_by_season, dataset_digest = load_games(
        args.dataset)

    population = []
    recon = {str(s): {"corpus_reg": reg_by_season[s], "scored": 0,
                      "excluded_no_final_score": 0,
                      "paired_eligible": 0,
                      "paired_ineligible_lt30_prior": 0}
             for s in SEASONS}
    counts = Counter()
    counts["corpus_rows_total"] = total_rows
    inputs = []  # every completed REG game 2017-2025 (inputs for v2/B3)
    for g in games_all:
        done = g["home_score"] is not None and g["away_score"] is not None
        if done:
            inputs.append(g)
        if g["season"] not in SEASONS:
            continue
        if not done:
            counts["excluded_no_final_score"] += 1
            recon[str(g["season"])]["excluded_no_final_score"] += 1
            continue
        population.append(g)
        recon[str(g["season"])]["scored"] += 1
        counts["scored"] += 1
    counts["burn_in_input_games_2017"] = sum(
        1 for g in inputs if g["season"] in BURN_IN_SEASONS)

    # FROZEN provider (Stage 2 verbatim: same-season samples only).
    samples = defaultdict(list)
    for g in population:
        samples[g["home"]].append(
            (g["kickoff"], g["season"], g["home_score"], g["away_score"]))
        samples[g["away"]].append(
            (g["kickoff"], g["season"], g["away_score"], g["home_score"]))
    provider = CorpusProvider(samples)

    clim_starts = defaultdict(list)
    clim_totals = defaultdict(list)
    for g in population:
        clim_starts[g["season"]].append(g["kickoff"])
        clim_totals[g["season"]].append(g["home_score"] + g["away_score"])
    season_totals_all = defaultdict(list)  # full-season totals (B3 S-1 pool)
    for g in inputs:
        season_totals_all[g["season"]].append(g["home_score"] + g["away_score"])

    # ---- v2 anchors: league level strictly before each input game,
    # window = seasons {s-1, s}; identical kickoffs never see each other.
    inputs.sort(key=lambda g: (g["kickoff"], g["away"], g["home"]))
    in_kicks = [g["kickoff"] for g in inputs]

    def window_prior(kickoff, season):
        j = bisect.bisect_left(in_kicks, kickoff)
        return [inputs[t] for t in range(j)
                if inputs[t]["season"] in (season - 1, season)]

    anchor = {}
    for g in inputs:
        prior = window_prior(g["kickoff"], g["season"])
        anchor[id(g)] = v2.league_level(
            [(p["home_score"] + p["away_score"]) / 2.0 for p in prior])

    def v2_prediction(g):
        prior = window_prior(g["kickoff"], g["season"])
        league = v2.league_level(
            [(p["home_score"] + p["away_score"]) / 2.0 for p in prior])

        def hist(team):
            out = []
            for p in prior:
                a = anchor[id(p)]
                if p["home"] == team:
                    out.append((p["season"], p["home_score"] - a,
                                p["away_score"] - a))
                elif p["away"] == team:
                    out.append((p["season"], p["away_score"] - a,
                                p["home_score"] - a))
            return out
        hres = v2.team_residuals(hist(g["home"]), g["season"])
        ares = v2.team_residuals(hist(g["away"]), g["season"])
        e_home, e_away = v2.expected_scores(league, hres, ares)
        return league, e_home, e_away

    _, sd_total, _, _ = fm.PRIORS["NFL"]
    rows, audit, model_only = [], [], []
    band_sums = {line: {"n": 0, "cand": 0.0, "frozen": 0.0, "b2": 0.0,
                        "b3": 0.0} for line in TOTAL_BAND_GRID}
    for g in population:
        context, _ko, _notes = fm.context_for(
            "NFL", g["away"], g["home"], g["kickoff"], provider, {})
        home_mean_f, away_mean_f = fm.score_means("NFL", context)
        frozen_total_mean = home_mean_f + away_mean_f
        total = g["home_score"] + g["away_score"]
        iso = g["kickoff"].date().isocalendar()
        week = f"{iso[0]}-W{iso[1]:02d}"
        starts = clim_starts[g["season"]]
        idx = bisect.bisect_left(starts, g["kickoff"])
        eligible = idx >= CLIM_MIN_PRIOR
        league, e_home, e_away = v2_prediction(g)
        cand_mean = e_home + e_away
        crps_frozen = crps_normal(frozen_total_mean, sd_total, total)
        crps_cand = crps_normal(cand_mean, v2.TOTAL_SD, total)
        model_only.append({"crps_cand": crps_cand, "crps_frozen": crps_frozen})
        base = {"date": g["kickoff"].isoformat(), "season": g["season"],
                "away": g["away"], "home": g["home"],
                "away_score": g["away_score"], "home_score": g["home_score"],
                "total": total,
                "frozen_total_mean": round(frozen_total_mean, 3),
                "cand_total_mean": round(cand_mean, 9),
                "league_level": round(league, 9),
                "e_home": round(e_home, 9), "e_away": round(e_away, 9),
                "clim_prior_n": idx, "paired_eligible": eligible,
                "crps_total_frozen": round(crps_frozen, 6),
                "crps_total_cand": round(crps_cand, 6)}
        if not eligible:
            counts["paired_ineligible_lt30_prior"] += 1
            recon[str(g["season"])]["paired_ineligible_lt30_prior"] += 1
            audit.append(base)
            continue
        counts["paired_eligible"] += 1
        recon[str(g["season"])]["paired_eligible"] += 1
        prior_same = clim_totals[g["season"]][:idx]
        pmf2 = {v: c / idx for v, c in Counter(prior_same).items()}
        b3_pool = season_totals_all[g["season"] - 1] + prior_same
        pmf3 = {v: c / len(b3_pool) for v, c in Counter(b3_pool).items()}
        crps_b2 = crps_empirical_int(pmf2, total)
        crps_b3 = crps_empirical_int(pmf3, total)
        rows.append({"season": g["season"], "week": week, "total": total,
                     "cand_mean": cand_mean, "crps_frozen": crps_frozen,
                     "crps_b2": crps_b2, "crps_b3": crps_b3,
                     "crps_cand": crps_cand})
        for line in TOTAL_BAND_GRID:
            y = 1 if total > line else 0
            bs = band_sums[line]
            bs["n"] += 1
            bs["cand"] += (1.0 - fm.cdf(line, cand_mean, v2.TOTAL_SD) - y) ** 2
            bs["frozen"] += (1.0 - fm.cdf(line, frozen_total_mean, sd_total) - y) ** 2
            bs["b2"] += (sum(1 for v in prior_same if v > line) / idx - y) ** 2
            bs["b3"] += (sum(1 for v in b3_pool if v > line) / len(b3_pool) - y) ** 2
        audit.append({**base, "crps_total_b2": round(crps_b2, 6),
                      "crps_total_b3": round(crps_b3, 6)})

    repro = paired_summary(rows, "crps_frozen", "crps_b2")
    rd = repro["paired_diff"]
    repro_check = {
        "n_scored": counts["scored"], "n_paired": repro["n"],
        "frozen_mean": repro["crps_frozen_mean"], "b2_mean": repro["crps_b2_mean"],
        "delta": rd["mean_diff"], "ci95": [rd["ci95_lo"], rd["ci95_hi"]],
        "expected": STAGE2,
        "passed": (
            counts["scored"] == STAGE2["n_scored"]
            and repro["n"] == STAGE2["n_paired"]
            and abs(repro["crps_frozen_mean"] - STAGE2["frozen_mean"]) < REPRO_TOL
            and abs(repro["crps_b2_mean"] - STAGE2["b2_mean"]) < REPRO_TOL
            and abs(rd["mean_diff"] - STAGE2["delta"]) < REPRO_TOL
            and abs(rd["ci95_lo"] - STAGE2["ci_lo"]) < REPRO_TOL
            and abs(rd["ci95_hi"] - STAGE2["ci_hi"]) < REPRO_TOL)}
    if not repro_check["passed"]:
        raise SystemExit("STAGE2_REPRODUCTION_FAILED — no candidate verdict. "
                         + json.dumps(repro_check))

    legs = {}
    for base_key in ("crps_frozen", "crps_b2", "crps_b3"):
        pooled = paired_summary(rows, "crps_cand", base_key)
        per = {str(s): paired_summary([r for r in rows if r["season"] == s],
                                      "crps_cand", base_key) for s in SEASONS}
        d = pooled["paired_diff"]
        legs[base_key] = {"pooled": pooled, "by_season": per,
                          "beats": bool(d and d["ci95_hi"] < 0),
                          "losing_seasons_ci_gt0": [
                              s for s, v in per.items()
                              if v.get("paired_diff") and v["paired_diff"]["ci95_lo"] > 0]}
    passed = all(v["beats"] for v in legs.values())
    verdict = "SCREEN_PASSED" if passed else "DOES_NOT_BEAT_BASELINE"
    failing = [k for k, v in legs.items() if not v["beats"]]
    level_bias = {str(s): statistics.mean([r["cand_mean"] - r["total"]
                  for r in rows if r["season"] == s]) for s in SEASONS}
    band_out = [{"total_line": line, "n": b["n"],
                 **{f"brier_{k}": b[k] / b["n"] for k in ("cand", "frozen", "b2", "b3")}}
                for line, b in band_sums.items()]
    results = {
        "item": "NFL_TOTALS_LEVEL_V2_PART_A",
        "label": "RESEARCH_EVIDENCE_DIAGNOSTIC_SCREEN_REUSED_DEVELOPMENT_DATA",
        "evidence_class": ("Part A diagnostic screen on 2018-2025 data already "
                           "used by Stage 2 N3 and LEVEL v1. NOT out-of-sample "
                           "validation, NOT a market verdict, NOT a promotion "
                           "input. A pass only earns Part B (2026 prospective)."),
        "contract_note": ("Promotes nothing; wires nothing; WATCH_NFL_TOTAL_PRIOR_ONLY "
                          "unchanged."),
        "prereg": {"file": "PREREG_NFL_TOTALS_LEVEL_V2.md", "sha256": prereg_digest,
                   "sha256_verified_at_load": True,
                   "lock_commit": "9e94c10074a74b8ec0732f203bb6009276660af8"},
        "model_identity": {
            "candidate": "sportsedge/research/nfl_totals_level_v2.py",
            "candidate_blob": git_blob_id(REPO_ROOT / "sportsedge" / "research"
                                          / "nfl_totals_level_v2.py"),
            "constants": {"league_half_life_games": v2.LEAGUE_HALF_LIFE_GAMES,
                          "team_half_life_games": v2.TEAM_HALF_LIFE_GAMES,
                          "season_carryover": v2.SEASON_CARRYOVER,
                          "kappa": v2.KAPPA, "league_fallback": v2.LEAGUE_FALLBACK,
                          "hfa_half": v2.HFA_HALF, "total_sd_fixed": v2.TOTAL_SD},
            "frozen_prior": {"file": "artifacts/free_models.py",
                             "blob": EXPECTED_MODEL_BLOB,
                             "blob_verified_at_load": True}},
        "dataset": {"sha256": dataset_digest, "sha256_verified_at_load": True,
                    "source": "nflverse/nfldata data/games.csv @ 4c15d52430866a57c1e7118177d8aea2e0905ab0",
                    "games_total_in_file": total_rows,
                    "fields_not_read": "spread/total/moneyline columns"},
        "implementation_notes": [
            "Residual anchors for 2017 burn-in games use only strictly-prior 2017 "
            "games (2016 is outside the declared input window and is not loaded); "
            "the earliest 2017 anchors therefore use the 22.0 fallback. This "
            "affects only the carried prior-season residuals of 2018 fixtures."],
        "population_reconciliation_by_season": recon,
        "counts": dict(counts),
        "reproduction_precondition": repro_check,
        "primary_metric": "total-distribution CRPS, paired subset",
        "legs": {"vs_FROZEN": legs["crps_frozen"], "vs_B2": legs["crps_b2"],
                 "vs_B3": legs["crps_b3"]},
        "gate": {"rule": "SCREEN_PASSED iff pooled paired dCRPS CI entirely < 0 vs FROZEN, B2 and B3",
                 "failing_legs": failing},
        "verdict": verdict,
        "means": {"cand": statistics.mean(r["crps_cand"] for r in rows),
                  "frozen": statistics.mean(r["crps_frozen"] for r in rows),
                  "b2": statistics.mean(r["crps_b2"] for r in rows),
                  "b3": statistics.mean(r["crps_b3"] for r in rows),
                  "n_paired": len(rows)},
        "level_mean_signed_error_by_season": level_bias,
        "resid_sd": statistics.pstdev([r["total"] - r["cand_mean"] for r in rows]),
        "secondary_brier_over_grid": band_out,
        "model_only_all_scored": {
            "n": len(model_only),
            "crps_cand": statistics.mean(r["crps_cand"] for r in model_only),
            "crps_frozen": statistics.mean(r["crps_frozen"] for r in model_only)},
        "bootstrap": {"blocks": "ISO calendar weeks", "resamples": BOOTSTRAP_RESAMPLES,
                      "seed": BOOTSTRAP_SEED},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    text = json.dumps(results, sort_keys=True, separators=(",", ":"))
    if args.out:
        Path(args.out).write_text(text + "\n")
    if args.audit:
        fields = ["date", "season", "away", "home", "away_score", "home_score",
                  "total", "frozen_total_mean", "cand_total_mean", "league_level",
                  "e_home", "e_away", "clim_prior_n", "paired_eligible",
                  "crps_total_frozen", "crps_total_cand", "crps_total_b2",
                  "crps_total_b3"]
        with open(args.audit, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(audit)
    print(json.dumps({"verdict": verdict, "means": results["means"],
                      "failing_legs": failing}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
