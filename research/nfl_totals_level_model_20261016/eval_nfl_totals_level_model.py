#!/usr/bin/env python3
"""RESEARCH_EVIDENCE — NFL totals LEVEL model evaluation.

HARD LABELS (read before citing any number from this script):

* RETROSPECTIVE CALIBRATION on DEVELOPMENT data (2018–2025).
  NOT a market verdict, NOT validation, NOT a promotion input.
  Promotes NOTHING; changes no model, registry, card label, or
  threshold. The production NFL totals path keeps
  WATCH_NFL_TOTAL_PRIOR_ONLY whatever this run shows.
* Preregistration: PREREG_NFL_TOTALS_LEVEL_MODEL.md in this
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

Candidate: sportsedge/research/nfl_totals_level_model.py
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

from sportsedge.research import nfl_totals_level_model as lvl  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "free_models_pinned", REPO_ROOT / "artifacts" / "free_models.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261015
CLIM_MIN_PRIOR = 30
SEASONS = list(range(2018, 2026))
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
    prereg = HERE / "PREREG_NFL_TOTALS_LEVEL_MODEL.md"
    digest = sha256_of(prereg)
    if locked.get("PREREG_NFL_TOTALS_LEVEL_MODEL.md") != digest:
        raise SystemExit(
            f"PREREG_SHA256_MISMATCH: got {digest}, locked "
            f"{locked.get('PREREG_NFL_TOTALS_LEVEL_MODEL.md')} — "
            "refusing to score against an unlocked preregistration.")
    ref = HERE / "SPEC_N1_N3_REFERENCE.md"
    if sha256_of(ref) != \
            "9e005933cda2cabfbc673140ab5093f9395d5032e3965d1037caa90e65828d60":
        raise SystemExit("STAGE2_SPEC_REFERENCE_MISMATCH — refusing.")
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
        if season not in SEASONS:
            continue
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
    for g in games_all:
        if g["home_score"] is None or g["away_score"] is None:
            counts["excluded_no_final_score"] += 1
            recon[str(g["season"])]["excluded_no_final_score"] += 1
            continue
        population.append(g)
        recon[str(g["season"])]["scored"] += 1
        counts["scored"] += 1

    # Frozen-prior provider samples (Stage 2): per team, chronological
    # (kickoff, season, own pts, opp pts).
    samples = defaultdict(list)
    for g in population:
        samples[g["home"]].append(
            (g["kickoff"], g["season"], g["home_score"], g["away_score"]))
        samples[g["away"]].append(
            (g["kickoff"], g["season"], g["away_score"], g["home_score"]))
    provider = CorpusProvider(samples)

    # Per-season kickoff-ordered pools (Stage 2): climatology totals +
    # league-rate points inputs. bisect_left gives strictly-prior
    # games only — identical instants never see each other.
    clim_starts = defaultdict(list)
    clim_totals = defaultdict(list)
    for g in population:
        clim_starts[g["season"]].append(g["kickoff"])
        clim_totals[g["season"]].append(g["home_score"] + g["away_score"])

    # Per-team chronological game lists for the level model: bisect on
    # the team's kickoff list gives strictly-prior games (batch rule).
    team_starts = defaultdict(list)
    team_games = defaultdict(list)  # team -> [(pf, pa)] from its view
    for g in population:
        team_starts[g["home"]].append(g["kickoff"])
        team_games[g["home"]].append((g["home_score"], g["away_score"]))
        team_starts[g["away"]].append(g["kickoff"])
        team_games[g["away"]].append((g["away_score"], g["home_score"]))

    _, sd_total, _, _ = fm.PRIORS["NFL"]
    rows = []        # paired-eligible rows
    model_only = []  # every scored game
    audit = []
    band_sums = {line: {"n": 0, "cand": 0.0, "frozen": 0.0, "b2": 0.0}
                 for line in TOTAL_BAND_GRID}
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

        # --- candidate: level model (prereg §3) ---
        prior_totals_list = clim_totals[g["season"]][:idx]
        # league rate from strictly-prior totals: points / (2*games)
        league = (sum(prior_totals_list) / (2.0 * idx)) if idx else \
            lvl.LEAGUE_FALLBACK
        h_idx = bisect.bisect_left(team_starts[g["home"]], g["kickoff"])
        a_idx = bisect.bisect_left(team_starts[g["away"]], g["kickoff"])
        home_record = lvl.team_record(team_games[g["home"]][:h_idx])
        away_record = lvl.team_record(team_games[g["away"]][:a_idx])
        e_home, e_away = lvl.expected_scores(home_record, away_record,
                                             league)
        cand_total_mean = lvl.total_mean(e_home, e_away)

        crps_frozen = crps_normal(frozen_total_mean, sd_total, total)
        crps_cand = crps_normal(cand_total_mean, lvl.TOTAL_SD, total)
        model_only.append({"season": g["season"], "week": week,
                           "crps_frozen": crps_frozen,
                           "crps_cand": crps_cand})
        base = {"date": g["kickoff"].isoformat(), "season": g["season"],
                "away": g["away"], "home": g["home"],
                "away_score": g["away_score"],
                "home_score": g["home_score"], "total": total,
                "frozen_total_mean": round(frozen_total_mean, 3),
                "cand_total_mean": round(cand_total_mean, 3),
                "e_home": round(e_home, 3), "e_away": round(e_away, 3),
                "league_rate": round(league, 6),
                "clim_prior_n": idx, "paired_eligible": eligible,
                "crps_total_frozen": round(crps_frozen, 6),
                "crps_total_cand": round(crps_cand, 6)}
        if not eligible:
            counts["paired_ineligible_lt30_prior"] += 1
            recon[str(g["season"])]["paired_ineligible_lt30_prior"] += 1
            audit.append({**base, "crps_total_b2": ""})
            continue
        counts["paired_eligible"] += 1
        recon[str(g["season"])]["paired_eligible"] += 1
        pmf_t = {v: c / idx for v, c in Counter(prior_totals_list).items()}
        crps_b2 = crps_empirical_int(pmf_t, total)
        rows.append({"season": g["season"], "week": week,
                     "total": total, "e_home": e_home, "e_away": e_away,
                     "home_score": g["home_score"],
                     "away_score": g["away_score"],
                     "cand_mean": cand_total_mean,
                     "frozen_mean": frozen_total_mean,
                     "crps_frozen": crps_frozen, "crps_b2": crps_b2,
                     "crps_cand": crps_cand})
        # Secondary: Brier of OVER at the fixed half-line grid (§4).
        y_over_cache = {}
        for line in TOTAL_BAND_GRID:
            y_over = 1 if total > line else 0
            p_cand = 1.0 - fm.cdf(line, cand_total_mean, lvl.TOTAL_SD)
            p_frozen = 1.0 - fm.cdf(line, frozen_total_mean, sd_total)
            p_b2 = sum(1 for v in prior_totals_list if v > line) / idx
            band_sums[line]["n"] += 1
            band_sums[line]["cand"] += (p_cand - y_over) ** 2
            band_sums[line]["frozen"] += (p_frozen - y_over) ** 2
            band_sums[line]["b2"] += (p_b2 - y_over) ** 2
            y_over_cache[line] = y_over
        audit.append({**base, "crps_total_b2": round(crps_b2, 6)})

    # ---- Reproduction precondition (prereg section 1) ----
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
            and abs(rd["ci95_hi"] - STAGE2["ci_hi"]) < REPRO_TOL),
    }
    if not repro_check["passed"]:
        raise SystemExit(
            "STAGE2_REPRODUCTION_FAILED — refusing to report a "
            f"candidate verdict. Check: {json.dumps(repro_check)}")

    def by_season(fn, source):
        return {str(s): fn([r for r in source if r["season"] == s])
                for s in SEASONS}

    cand_vs_frozen = paired_summary(rows, "crps_cand", "crps_frozen")
    cand_vs_b2 = paired_summary(rows, "crps_cand", "crps_b2")
    cvf_by = by_season(
        lambda sub: paired_summary(sub, "crps_cand", "crps_frozen"), rows)
    cvb_by = by_season(
        lambda sub: paired_summary(sub, "crps_cand", "crps_b2"), rows)

    def leg_beats(summary):
        d = summary.get("paired_diff")
        return bool(d and d["ci95_hi"] < 0)

    beats_frozen = leg_beats(cand_vs_frozen)
    beats_b2 = leg_beats(cand_vs_b2)
    verdict = ("BEATS_BASELINE" if (beats_frozen and beats_b2)
               else "DOES_NOT_BEAT_BASELINE")

    # ---- Section 6 error decomposition (paired subset) ----
    errs = [r["cand_mean"] - r["total"] for r in rows]
    resid = [r["total"] - r["cand_mean"] for r in rows]
    resid_sd = statistics.pstdev(resid) if len(resid) > 1 else None
    home_err = [r["e_home"] - r["home_score"] for r in rows]
    away_err = [r["e_away"] - r["away_score"] for r in rows]
    if len(rows) > 2:
        mh, ma = statistics.mean(home_err), statistics.mean(away_err)
        num = sum((a - mh) * (b - ma) for a, b in zip(home_err, away_err))
        den = math.sqrt(sum((a - mh) ** 2 for a in home_err)
                        * sum((b - ma) ** 2 for b in away_err))
        split_corr = (num / den) if den else None
    else:
        split_corr = None
    # Diagnostic-only: candidate means under per-season refit sd.
    diag = {}
    for s in SEASONS:
        sub = [r for r in rows if r["season"] == s]
        if len(sub) < 3:
            continue
        s_sd = statistics.pstdev([r["total"] - r["cand_mean"] for r in sub])
        diag[str(s)] = {
            "n": len(sub), "refit_sd": s_sd,
            "crps_cand_fixed_sd": sum(r["crps_cand"] for r in sub) / len(sub),
            "crps_cand_refit_sd_diag": sum(
                crps_normal(r["cand_mean"], s_sd, r["total"])
                for r in sub) / len(sub),
            "mean_signed_error": sum(
                r["cand_mean"] - r["total"] for r in sub) / len(sub)}
    level_by_season = {str(s): (sum(r["cand_mean"] - r["total"]
                                    for r in rows if r["season"] == s)
                                / max(1, sum(1 for r in rows
                                             if r["season"] == s)))
                       for s in SEASONS}

    band_out = []
    for line in TOTAL_BAND_GRID:
        bs = band_sums[line]
        band_out.append({
            "total_line": line, "n": bs["n"],
            "brier_cand": bs["cand"] / bs["n"] if bs["n"] else None,
            "brier_frozen": bs["frozen"] / bs["n"] if bs["n"] else None,
            "brier_b2": bs["b2"] / bs["n"] if bs["n"] else None})

    mo = {"n": len(model_only)}
    if model_only:
        mo["crps_cand_all_scored"] = sum(
            r["crps_cand"] for r in model_only) / len(model_only)
        mo["crps_frozen_all_scored"] = sum(
            r["crps_frozen"] for r in model_only) / len(model_only)

    results = {
        "item": "NFL_TOTALS_LEVEL_MODEL",
        "label": "RESEARCH_EVIDENCE_RETROSPECTIVE_CALIBRATION_NOT_VALIDATION",
        "evidence_class": (
            "RETROSPECTIVE CALIBRATION on 2018-2025 development data, "
            "against the Stage 2 N3 baselines. NOT a market verdict, "
            "NOT validation, NOT a promotion input."),
        "contract_note": (
            "Promotes nothing; wires nothing. The production NFL "
            "totals path keeps WATCH_NFL_TOTAL_PRIOR_ONLY / "
            "NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING whatever this "
            "run shows; any wiring is a separate owner ruling."),
        "prereg": {"file": "PREREG_NFL_TOTALS_LEVEL_MODEL.md",
                   "sha256": prereg_digest,
                   "sha256_verified_at_load": True},
        "stage2_reference": {
            "spec": "mlb_market_legs_20261014/SPEC_N1_N3_NFL_CALIBRATION.md",
            "spec_sha256": "9e005933cda2cabfbc673140ab5093f9395d5032e3965d1037caa90e65828d60",
            "item": "N3", "stage2_verdict_frozen_vs_b2": "DOES_NOT_BEAT_BASELINE"},
        "model_identity": {
            "candidate": "sportsedge/research/nfl_totals_level_model.py",
            "candidate_constants": {"kappa": lvl.KAPPA,
                                    "league_fallback": lvl.LEAGUE_FALLBACK,
                                    "hfa_half": lvl.HFA_HALF,
                                    "total_sd_fixed": lvl.TOTAL_SD},
            "frozen_prior": {"file": "artifacts/free_models.py",
                             "blob": EXPECTED_MODEL_BLOB,
                             "blob_verified_at_load": True},
        },
        "dataset": {"file": "nfl_games.csv (local, not in repo)",
                    "sha256": dataset_digest,
                    "sha256_verified_at_load": True,
                    "games_total_in_file": total_rows,
                    "fields_not_read": "spread/total/moneyline columns"},
        "population_reconciliation_by_season": recon,
        "counts": dict(counts),
        "reproduction_precondition": repro_check,
        "primary_metric": "total-distribution CRPS, paired subset",
        "candidate_vs_frozen": cand_vs_frozen,
        "candidate_vs_frozen_by_season": cvf_by,
        "candidate_vs_b2": cand_vs_b2,
        "candidate_vs_b2_by_season": cvb_by,
        "gate": {"rule": ("BEATS_BASELINE iff pooled paired dCRPS CI "
                          "entirely < 0 vs FROZEN and vs B2"),
                 "beats_frozen": beats_frozen, "beats_b2": beats_b2},
        "verdict": verdict,
        "secondary_brier_over_grid": band_out,
        "error_decomposition": {
            "level_mean_signed_error_pooled": statistics.mean(errs),
            "level_mean_signed_error_by_season": level_by_season,
            "variance_resid_sd_vs_fixed": {"resid_sd": resid_sd,
                                           "fixed_sd": lvl.TOTAL_SD},
            "variance_diagnostic_refit_sd_by_season": diag,
            "team_split": {
                "mae_home": statistics.mean(abs(e) for e in home_err),
                "mae_away": statistics.mean(abs(e) for e in away_err),
                "team_error_correlation": split_corr},
        },
        "model_only_all_scored": mo,
        "bootstrap": {"blocks": "ISO calendar weeks",
                      "resamples": BOOTSTRAP_RESAMPLES,
                      "seed": BOOTSTRAP_SEED},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    text = json.dumps(results, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    if args.audit:
        fields = ["date", "season", "away", "home", "away_score",
                  "home_score", "total", "frozen_total_mean",
                  "cand_total_mean", "e_home", "e_away", "league_rate",
                  "clim_prior_n", "paired_eligible",
                  "crps_total_frozen", "crps_total_cand", "crps_total_b2"]
        with open(args.audit, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(audit)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
