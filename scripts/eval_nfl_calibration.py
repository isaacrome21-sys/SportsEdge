#!/usr/bin/env python3
"""RESEARCH_EVIDENCE — NFL ML / Spread / Total calibration legs (N1–N3).

HARD LABELS (read before citing any number from this script):

* This is a RETROSPECTIVE CALIBRATION evaluation on DEVELOPMENT data
  (2018–2025). It is NOT a market verdict, NOT validation, and NOT a
  promotion input. It promotes NOTHING and changes no model, registry,
  or threshold.
* The market legs are FORWARD_ONLY_BY_DESIGN: no historical paired NFL
  odds corpus exists in-repo under the project's paired contract, and
  none is scored here. The schedule corpus carries single-source line
  columns; they are NOT read by this evaluator (only the manifested
  fields below are ever accessed) — the classification is a property
  of the evidence standard, not of what a CSV happens to contain.
* N3 caveat (verbatim from the engine itself, calculate()):
  NFL totals carry status WATCH_NFL_TOTAL_PRIOR_ONLY, reason
  NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING:22_PTS_PER_TEAM_PLUS_MARGIN_FORM_ONLY.
  The total mean is a 22-points-per-team prior adjusted only by the
  margin-form rating split — there is no absolute scoring-rate model.

Spec: mlb_market_legs_20261014/SPEC_N1_N3_NFL_CALIBRATION.md
(SHA-256 9e005933cda2cabfbc673140ab5093f9395d5032e3965d1037caa90e65828d60),
written and hashed before any NFL score was computed by this lane.
The evaluator verifies that hash, the dataset SHA-256, and the model
blob hash at load and refuses to score on any mismatch.

Model identity: artifacts/free_models.py at main
83e0c396a4761ea3de80583be5e61e8ca2e07f9a (blob
253b0c6d91840c906941216be117f2acc1497a57, identical at the Stage 1 pin
2a713380c) — Lane A via the module's own context_for() / score_means()
/ model_probability("NFL", ...), with a corpus-backed provider
implementing the production PublicContext.schedule() semantics of the
spec §2: same-season completed games strictly before kickoff, sorted
descending, first 5; the season of a Jan/Feb kickoff is the preceding
fall's. Declared neutralizations (spec §2): injury_points = 0.0 and
weather_total_adj = 0.0 for every game. Team keying is by the corpus's
per-season abbreviation (exact, spec §2). Games sharing an identical
kickoff instant are batch-processed: neither sees the other, in either
the rating samples or the climatology pools.
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
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "free_models_pinned", REPO_ROOT / "artifacts" / "free_models.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261015
EPS = 1e-15
PARITY_GAMES = 25
EXPECTED_DATASET_SHA256 = \
    "a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284"
SPEC_SHA256 = \
    "9e005933cda2cabfbc673140ab5093f9395d5032e3965d1037caa90e65828d60"
SPEC_RELPATH = "mlb_market_legs_20261014/SPEC_N1_N3_NFL_CALIBRATION.md"
MAIN_COMMIT = "83e0c396a4761ea3de80583be5e61e8ca2e07f9a"
EXPECTED_MODEL_BLOB = "253b0c6d91840c906941216be117f2acc1497a57"
CLIM_MIN_PRIOR = 30
SEASONS = list(range(2018, 2026))
COVER_GRID = [-7.5, -3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5, 7.5]
N3_CAVEAT_STATUS = "WATCH_NFL_TOTAL_PRIOR_ONLY"
N3_CAVEAT_REASON = ("NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING:"
                    "22_PTS_PER_TEAM_PLUS_MARGIN_FORM_ONLY")
ET = ZoneInfo("America/New_York")
# Only these corpus fields are ever accessed (spec §4). The file's
# spread / total / moneyline columns are never read.
USED_FIELDS = ("season", "game_type", "gameday", "gametime",
               "away_team", "home_team", "away_score", "home_score")


def git_blob_sha256less(path):
    """Git blob id (SHA-1) of a file, computed without a git subprocess."""
    data = Path(path).read_bytes()
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def verify_spec_hash():
    spec_path = REPO_ROOT / SPEC_RELPATH
    digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    if digest != SPEC_SHA256:
        raise SystemExit(
            f"SPEC_SHA256_MISMATCH: got {digest}, expected {SPEC_SHA256} "
            "— refusing to score against a spec that is not the "
            "SHA-locked one.")
    return digest


def derived_season(kickoff):
    """Production schedule() season rule: Jan/Feb football belongs to
    the preceding fall's season (pinned code, PublicContext.schedule)."""
    return kickoff.year - 1 if kickoff.month <= 2 else kickoff.year


class CorpusProvider:
    """Corpus-backed provider with the production provider's semantics
    (spec §2, the M1/M2 pattern).

    fixture = the corpus game itself; identify = corpus team key;
    schedule = same-season completed games strictly before kickoff,
    tuple-sorted descending, first 5. injury_points / weather are the
    two declared neutralizations of spec §2: 0.0 for every team. The
    injury status string carries the production receipt prefix so the
    pinned calculate() NFL critical-context gate can be exercised end
    to end; the points value is exactly the declared 0.0.
    """

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
        hs, aws = row["home_score"], row["away_score"]
        gametime = row["gametime"] or "00:00"
        kickoff = datetime.fromisoformat(
            f"{row['gameday']}T{gametime}").replace(tzinfo=ET)
        games.append({
            "kickoff": kickoff,
            "season": season,
            "away": row["away_team"],
            "home": row["home_team"],
            "away_score": int(aws) if aws not in (None, "") else None,
            "home_score": int(hs) if hs not in (None, "") else None,
        })
    games.sort(key=lambda g: (g["kickoff"], g["away"] or "", g["home"] or ""))
    return games, total_rows, reg_by_season, digest


def brier(p, y):
    return (p - y) ** 2


def logloss(p, y):
    p = min(max(p, EPS), 1.0 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def block_bootstrap_ci(diffs_by_block, resamples=BOOTSTRAP_RESAMPLES,
                       seed=BOOTSTRAP_SEED):
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
            "ci95_hi": means[min(resamples - 1, int(0.975 * resamples))],
            "n_blocks": len(blocks), "resamples": resamples}


def paired_summary(rows, model_key, base_key):
    """Mean model / baseline scores + paired block-bootstrap CI of the
    per-game difference (model − baseline; negative = model better)."""
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


def n1_summary(rows):
    out = {"n": len(rows)}
    if not rows:
        return out
    pairs = [("brier", brier), ("logloss", logloss)]
    out["brier_model"] = sum(brier(r["p_model"], r["y_win"]) for r in rows) / len(rows)
    out["brier_b1"] = sum(brier(r["p_b1"], r["y_win"]) for r in rows) / len(rows)
    out["logloss_model"] = sum(logloss(r["p_model"], r["y_win"]) for r in rows) / len(rows)
    out["logloss_b1"] = sum(logloss(r["p_b1"], r["y_win"]) for r in rows) / len(rows)
    for metric, fn in pairs:
        by_block = defaultdict(list)
        for r in rows:
            by_block[r["week"]].append(fn(r["p_model"], r["y_win"])
                                       - fn(r["p_b1"], r["y_win"]))
        out[f"paired_{metric}_diff"] = block_bootstrap_ci(by_block)
    return out


def calibration(rows):
    bins = []
    for lo in [i / 10 for i in range(10)]:
        hi = lo + 0.1
        sel = [r for r in rows if lo <= r["p_model"] < hi
               or (lo == 0.9 and r["p_model"] == 1.0)]
        if not sel:
            bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": 0,
                         "mean_pred": None, "observed": None})
            continue
        bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(sel),
                     "mean_pred": sum(r["p_model"] for r in sel) / len(sel),
                     "observed": sum(r["y_win"] for r in sel) / len(sel)})
    return bins


def crps_normal(mean, sd, y):
    """Closed-form CRPS of Normal(mean, sd) at observation y."""
    z = (y - mean) / sd
    phi = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    big_phi = fm.cdf(y, mean, sd)
    return sd * (z * (2.0 * big_phi - 1.0) + 2.0 * phi
                 - 1.0 / math.sqrt(math.pi))


def crps_empirical_int(pmf, y):
    """CRPS of an integer-supported empirical distribution (the M2
    crps_int construction): sum over k of (F(k) − 1{y <= k})^2."""
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


def lane_a_means(provider, game):
    context, _kickoff, _notes = fm.context_for(
        "NFL", game["away"], game["home"], game["kickoff"], provider, {})
    return fm.score_means("NFL", context), context


PARITY_MARKETS = (("ML", "HOME", None), ("SPREAD", "HOME", -3.5),
                  ("TOTAL", "OVER", 44.5))


def calculate_lane_a(provider, game, market, side, line, home_mean,
                     away_mean):
    """Drive the pinned calculate() for one row. Returns
    (view, None) or (None, blocked_record) when calculate() returns no
    Lane A view (its NFL critical-context gate fires before pricing)."""
    now = game["kickoff"] - timedelta(hours=1)
    row = {
        "sport": "NFL", "market": market, "side": side, "odds": -110,
        "away": game["away"], "home": game["home"],
        "commence_time": game["kickoff"].isoformat(),
        "quote_captured_at": (now - timedelta(seconds=60)).isoformat(),
    }
    if line is not None:
        row["line"] = line
    result = fm.calculate(row, provider, now)
    lanes = result.get("pricing_lanes") or {}
    view = lanes.get("lane_a_independent") or result.get(
        "independent_projection")
    if view is None:
        return None, {"status": result.get("status"),
                      "reason": result.get("reason")}
    p_pipeline, push_pipeline = fm.model_probability(
        "NFL", market, side, line, home_mean, away_mean)
    diff = abs(view["estimate_p"] - round(p_pipeline, 6))
    return {"estimate_p": view["estimate_p"], "push_p": view["push_p"],
            "p_pipeline": p_pipeline, "push_pipeline": push_pipeline,
            "diff": diff}, None


def run_parity(provider, games, means_by_id):
    """Spec §6 parity, in two recorded phases.

    Phase A — literal: the first 25 scored (population) games, three
    rows each (ML, SPREAD −3.5, TOTAL 44.5 OVER). calculate()'s NFL
    critical-context gate (HOME/AWAY_HISTORY_COUNT receipts) blocks
    every week-1 game before any Lane A view exists: the direct
    construction has no such gate and scores those games with the
    production 0.0 ratings. Those blocks are recorded, not hidden.

    Phase B — the probability-parity question §6 asks (does the Lane A
    path add anything the direct construction lacks?): the first 25
    scored games for which calculate() returns a Lane A view, three
    rows each; every probability must agree to < 1.5e-6. A probability
    mismatch in Phase B stops the run (the caller raises).
    """
    phase_a = {"games_attempted": 0, "row_checks": 0,
               "games_blocked_by_calculate_gate": 0,
               "blocked": [], "games_passed": 0, "max_diff": 0.0}
    for g in games[:PARITY_GAMES]:
        home_mean, away_mean = means_by_id[id(g)]
        phase_a["games_attempted"] += 1
        game_blocked = False
        for market, side, line in PARITY_MARKETS:
            view, blocked = calculate_lane_a(
                provider, g, market, side, line, home_mean, away_mean)
            if view is None:
                game_blocked = True
                phase_a["blocked"].append({
                    "date": g["kickoff"].isoformat(), "away": g["away"],
                    "home": g["home"], "market": market, **blocked})
                continue
            phase_a["row_checks"] += 1
            phase_a["max_diff"] = max(phase_a["max_diff"], view["diff"])
            if view["diff"] > 1.5e-6 or view["push_p"] != 0:
                raise AssertionError(
                    f"PARITY_PROBABILITY_MISMATCH phase A: {market} "
                    f"{g['away']} @ {g['home']} {g['kickoff']}: "
                    f"calculate {view['estimate_p']} vs pipeline "
                    f"{view['p_pipeline']} (diff {view['diff']})")
        if game_blocked:
            phase_a["games_blocked_by_calculate_gate"] += 1
        else:
            phase_a["games_passed"] += 1

    phase_b = {"games_checked": 0, "row_checks": 0, "max_diff": 0.0,
               "games_skipped_blocked": 0}
    for g in games:
        if phase_b["games_checked"] >= PARITY_GAMES:
            break
        home_mean, away_mean = means_by_id[id(g)]
        views = []
        blocked_any = False
        for market, side, line in PARITY_MARKETS:
            view, blocked = calculate_lane_a(
                provider, g, market, side, line, home_mean, away_mean)
            if view is None:
                blocked_any = True
                break
            views.append((market, view))
        if blocked_any:
            phase_b["games_skipped_blocked"] += 1
            continue
        for market, view in views:
            phase_b["row_checks"] += 1
            phase_b["max_diff"] = max(phase_b["max_diff"], view["diff"])
            if view["diff"] > 1.5e-6:
                raise AssertionError(
                    f"PARITY_PROBABILITY_MISMATCH phase B: {market} "
                    f"{g['away']} @ {g['home']} {g['kickoff']}: "
                    f"calculate {view['estimate_p']} vs pipeline "
                    f"{view['p_pipeline']} (diff {view['diff']})")
            if view["push_p"] != 0:
                raise AssertionError(
                    f"PARITY_PUSH_MISMATCH phase B: {market} at a "
                    f"half-line / ML must carry zero push mass, got "
                    f"{view['push_p']}")
        phase_b["games_checked"] += 1
    if phase_b["games_checked"] < PARITY_GAMES:
        raise AssertionError(
            f"PARITY_INCOMPLETE: only {phase_b['games_checked']} games "
            "returned a Lane A view; 25 required by spec §6.")
    return {"phase_a_first25_population_games": phase_a,
            "phase_b_first25_lane_a_returning_games": phase_b,
            "outcome": "PASSED_PROBABILITY_PARITY",
            "discrepancy_note": (
                "calculate() carries an NFL critical-context gate "
                "(HOME/AWAY_HISTORY_COUNT + injury receipts, "
                "BLOCKED_NFL_CRITICAL_CONTEXT_UNVERIFIED) that the "
                "direct context_for -> score_means -> model_probability "
                "construction lacks: it blocks week-1 games (0 prior "
                "same-season games) before pricing, while the direct "
                "construction scores them with the production 0.0 "
                "ratings — which is why the spec §5 population includes "
                "week-1 fixtures. The gate changes availability, not "
                "probabilities: wherever calculate() returns a Lane A "
                "view, its probabilities equal the direct pipeline "
                "(max diff recorded above). Phase A records the gate's "
                "effect on the literal first 25 population games; "
                "Phase B is the 25-game probability parity §6 asks "
                "for.")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default=None, help="results JSON path")
    ap.add_argument("--audit", default=None, help="per-game audit CSV path")
    args = ap.parse_args()

    spec_digest = verify_spec_hash()
    blob = git_blob_sha256less(REPO_ROOT / "artifacts" / "free_models.py")
    if blob != EXPECTED_MODEL_BLOB:
        raise SystemExit(
            f"MODEL_BLOB_MISMATCH: got {blob}, expected "
            f"{EXPECTED_MODEL_BLOB} — refusing to score a model that "
            "is not the pinned one.")

    games_all, total_rows, reg_by_season, dataset_digest = load_games(
        args.dataset)
    counts = Counter()
    counts["corpus_rows_total"] = total_rows

    population = []
    recon = {str(s): {"corpus_reg": reg_by_season[s], "scored": 0,
                      "excluded_no_final_score": 0,
                      "paired_eligible": 0,
                      "paired_ineligible_lt30_prior": 0}
             for s in SEASONS}
    for g in games_all:
        if g["home_score"] is None or g["away_score"] is None:
            counts["excluded_no_final_score"] += 1
            recon[str(g["season"])]["excluded_no_final_score"] += 1
            continue
        population.append(g)
        recon[str(g["season"])]["scored"] += 1
        counts["scored"] += 1

    # Rating samples: per team, (kickoff, season, own pts, opp pts) for
    # population games, in chronological order.
    samples = defaultdict(list)
    for g in population:
        samples[g["home"]].append(
            (g["kickoff"], g["season"], g["home_score"], g["away_score"]))
        samples[g["away"]].append(
            (g["kickoff"], g["season"], g["away_score"], g["home_score"]))
    provider = CorpusProvider(samples)

    # Climatology pools: per season, in kickoff order, (home margin,
    # game total) of population games. bisect_left on the kickoff list
    # gives strictly-prior games only — identical-instant games never
    # see each other (batch rule, spec §2).
    clim_starts = defaultdict(list)
    clim_margins = defaultdict(list)
    clim_totals = defaultdict(list)
    for g in population:
        clim_starts[g["season"]].append(g["kickoff"])
        clim_margins[g["season"]].append(g["home_score"] - g["away_score"])
        clim_totals[g["season"]].append(g["home_score"] + g["away_score"])

    # Lane A means for every population game (needed by parity first).
    means_by_id = {}
    contexts_by_id = {}
    for g in population:
        (hm, am), ctx = lane_a_means(provider, g)
        means_by_id[id(g)] = (hm, am)
        contexts_by_id[id(g)] = ctx

    parity = run_parity(provider, population, means_by_id)

    _, sd_total, sd_margin, _ = fm.PRIORS["NFL"]
    rows = []          # paired-eligible rows (identical subset, all items)
    audit = []
    model_only = []    # every scored game
    cover_sums = {line: {"n": 0, "brier_model": 0.0, "brier_b1": 0.0}
                  for line in COVER_GRID}
    for g in population:
        home_mean, away_mean = means_by_id[id(g)]
        ctx = contexts_by_id[id(g)]
        margin = g["home_score"] - g["away_score"]
        total = g["home_score"] + g["away_score"]
        y_win = 1 if margin > 0 else 0  # realized ties score y = 0 (§5)
        p_model, _push = fm.model_probability(
            "NFL", "ML", "HOME", None, home_mean, away_mean)
        crps_m_model = crps_normal(home_mean - away_mean, sd_margin, margin)
        crps_t_model = crps_normal(home_mean + away_mean, sd_total, total)
        iso = g["kickoff"].date().isocalendar()
        week = f"{iso[0]}-W{iso[1]:02d}"
        starts = clim_starts[g["season"]]
        idx = bisect.bisect_left(starts, g["kickoff"])
        eligible = idx >= CLIM_MIN_PRIOR
        base = {"date": g["kickoff"].isoformat(), "season": g["season"],
                "away": g["away"], "home": g["home"],
                "away_score": g["away_score"], "home_score": g["home_score"],
                "margin": margin, "total": total,
                "home_mean": round(home_mean, 3),
                "away_mean": round(away_mean, 3),
                "home_rating": ctx["home_rating"],
                "away_rating": ctx["away_rating"],
                "p_model_home_win": round(p_model, 6), "y_home_win": y_win,
                "clim_prior_n": idx, "paired_eligible": eligible,
                "brier_model": round(brier(p_model, y_win), 6),
                "logloss_model": round(logloss(p_model, y_win), 6),
                "crps_margin_model": round(crps_m_model, 6),
                "crps_total_model": round(crps_t_model, 6)}
        model_only.append({"season": g["season"], "week": week,
                           "brier_model": brier(p_model, y_win),
                           "logloss_model": logloss(p_model, y_win),
                           "crps_m_model": crps_m_model,
                           "crps_t_model": crps_t_model})
        if not eligible:
            counts["paired_ineligible_lt30_prior"] += 1
            recon[str(g["season"])]["paired_ineligible_lt30_prior"] += 1
            audit.append({**base, "p_b1_home_win": "",
                          "brier_b1": "", "logloss_b1": "",
                          "crps_margin_b1": "", "crps_total_b2": ""})
            continue
        counts["paired_eligible"] += 1
        recon[str(g["season"])]["paired_eligible"] += 1
        prior_margins = clim_margins[g["season"]][:idx]
        prior_totals = clim_totals[g["season"]][:idx]
        p_b1 = sum(1 for m in prior_margins if m > 0) / idx
        pmf_m = {v: c / idx for v, c in Counter(prior_margins).items()}
        pmf_t = {v: c / idx for v, c in Counter(prior_totals).items()}
        crps_m_b1 = crps_empirical_int(pmf_m, margin)
        crps_t_b2 = crps_empirical_int(pmf_t, total)
        rows.append({"season": g["season"], "week": week,
                     "p_model": p_model, "p_b1": p_b1, "y_win": y_win,
                     "crps_m_model": crps_m_model, "crps_m_b1": crps_m_b1,
                     "crps_t_model": crps_t_model, "crps_t_b2": crps_t_b2})
        # Descriptive cover Brier at the fixed half-line grid (§5):
        # event = home covers line L, i.e. margin + L > 0 (no pushes
        # at half lines). No market lines are used.
        for line in COVER_GRID:
            p_cov_model, _ = fm.model_probability(
                "NFL", "SPREAD", "HOME", line, home_mean, away_mean)
            p_cov_b1 = sum(1 for m in prior_margins if m + line > 0) / idx
            y_cov = 1 if margin + line > 0 else 0
            cover_sums[line]["n"] += 1
            cover_sums[line]["brier_model"] += brier(p_cov_model, y_cov)
            cover_sums[line]["brier_b1"] += brier(p_cov_b1, y_cov)
        audit.append({**base, "p_b1_home_win": round(p_b1, 6),
                      "brier_b1": round(brier(p_b1, y_win), 6),
                      "logloss_b1": round(logloss(p_b1, y_win), 6),
                      "crps_margin_b1": round(crps_m_b1, 6),
                      "crps_total_b2": round(crps_t_b2, 6)})

    def by_season(fn, source):
        return {str(s): fn([r for r in source if r["season"] == s])
                for s in SEASONS}

    n1_pooled = n1_summary(rows)
    n1_by = by_season(n1_summary, rows)
    n2_pooled = paired_summary(rows, "crps_m_model", "crps_m_b1")
    n2_by = by_season(lambda sub: paired_summary(sub, "crps_m_model",
                                                 "crps_m_b1"), rows)
    n3_pooled = paired_summary(rows, "crps_t_model", "crps_t_b2")
    n3_by = by_season(lambda sub: paired_summary(sub, "crps_t_model",
                                                 "crps_t_b2"), rows)

    def beats(*cis):
        return all(ci and ci["ci95_hi"] < 0 for ci in cis)

    n1_verdict = ("BEATS_BASELINE" if beats(
        n1_pooled.get("paired_brier_diff"),
        n1_pooled.get("paired_logloss_diff")) else "DOES_NOT_BEAT_BASELINE")
    n2_verdict = ("BEATS_BASELINE" if beats(n2_pooled.get("paired_diff"))
                  else "DOES_NOT_BEAT_BASELINE")
    n3_verdict = ("BEATS_BASELINE" if beats(n3_pooled.get("paired_diff"))
                  else "DOES_NOT_BEAT_BASELINE")

    cover_grid_out = []
    for line in COVER_GRID:
        s = cover_sums[line]
        cover_grid_out.append({
            "home_line": line, "n": s["n"],
            "brier_model": (s["brier_model"] / s["n"] if s["n"] else None),
            "brier_b1": (s["brier_b1"] / s["n"] if s["n"] else None),
            "brier_diff_model_minus_b1": (
                (s["brier_model"] - s["brier_b1"]) / s["n"]
                if s["n"] else None)})

    mo = {"n": len(model_only)}
    if model_only:
        mo["n1_brier_model"] = sum(r["brier_model"] for r in model_only) / len(model_only)
        mo["n1_logloss_model"] = sum(r["logloss_model"] for r in model_only) / len(model_only)
        mo["n2_crps_margin_model"] = sum(r["crps_m_model"] for r in model_only) / len(model_only)
        mo["n3_crps_total_model"] = sum(r["crps_t_model"] for r in model_only) / len(model_only)

    results = {
        "item": "N1_N3_NFL_CALIBRATION",
        "label": "RESEARCH_EVIDENCE_RETROSPECTIVE_CALIBRATION_NOT_VALIDATION",
        "evidence_class": (
            "RETROSPECTIVE CALIBRATION on 2018-2025 development data. "
            "Calibration legs only: the market legs are "
            "FORWARD_ONLY_BY_DESIGN (no historical paired NFL odds "
            "corpus under the paired contract; the corpus file's "
            "single-source line columns were NOT read). NOT a market "
            "verdict, NOT validation, NOT a promotion input."),
        "contract_note": (
            "Promotes nothing; no model, registry, or threshold change. "
            "Does not touch the G2 program (Attempt 2 unspent, owner's "
            "separate ruling). NFL rows keep their current labels, "
            "including WATCH_NFL_TOTAL_PRIOR_ONLY for totals whatever "
            "N3 shows."),
        "spec_sha256": spec_digest,
        "spec_sha256_verified_at_load": True,
        "model_identity": {
            "file": "artifacts/free_models.py",
            "main_commit": MAIN_COMMIT,
            "blob": blob,
            "blob_verified_at_load": True,
            "path": ("calculate() Lane A via context_for + score_means + "
                     "model_probability(NFL, ML/SPREAD/TOTAL)"),
            "priors_nfl": {"base_pts_per_team": 22.0, "total_sd": 13.5,
                           "margin_sd": 13.7, "hfa": 1.5},
            "declared_neutralizations": {
                "injury_points": 0.0, "weather_total_adj": 0.0},
        },
        "dataset": {
            "file": "nfl_games.csv (local copy ~/workspace/tmp/bt_data/nfl_games.csv)",
            "source": "nflverse/nfldata games.csv",
            "sha256": dataset_digest,
            "sha256_verified_at_load": True,
            "in_repo": False,
            "manifest": "mlb_market_legs_20261014/DATASET_MANIFEST_STAGE2.md",
            "games_total_in_file": total_rows,
            "fields_used_only": list(USED_FIELDS),
            "fields_not_read": ("spread_line, total_line, moneyline/odds "
                                "columns present in the file were never "
                                "accessed by this evaluator"),
        },
        "population_reconciliation_by_season": recon,
        "counts": dict(counts),
        "parity": parity,
        "parity_checks_passed": parity[
            "phase_b_first25_lane_a_returning_games"]["row_checks"],
        "items": {
            "N1_moneyline": {
                "metric": ("Brier + log loss of model P(home win) vs "
                           "B1 (expanding strictly-prior same-season "
                           "margin climatology) implied P(home margin > 0); "
                           "realized ties score y = 0, push mass excluded"),
                "gate": ("BEATS_BASELINE iff pooled paired dBrier CI "
                         "entirely < 0 AND dLogLoss CI entirely < 0"),
                "paired": n1_pooled,
                "by_season": n1_by,
                "verdict": n1_verdict,
            },
            "N2_spread": {
                "metric": ("Margin-distribution CRPS: Normal closed "
                           "form (sd 13.7) for the model vs empirical "
                           "CRPS for B1"),
                "gate": "BEATS_BASELINE iff pooled paired dCRPS CI entirely < 0",
                "paired": n2_pooled,
                "by_season": n2_by,
                "verdict": n2_verdict,
            },
            "N3_total": {
                "metric": ("Total-distribution CRPS: Normal closed "
                           "form (sd 13.5) for the model vs empirical "
                           "CRPS for B2 (total climatology)"),
                "gate": "BEATS_BASELINE iff pooled paired dCRPS CI entirely < 0",
                "engine_caveat": {"status": N3_CAVEAT_STATUS,
                                  "reason": N3_CAVEAT_REASON,
                                  "note": ("The total mean is a "
                                           "22-points-per-team prior "
                                           "adjusted only by the "
                                           "margin-form rating split — "
                                           "there is no absolute "
                                           "scoring-rate model. This "
                                           "caveat rides on every N3 "
                                           "number in this record.")},
                "paired": n3_pooled,
                "by_season": n3_by,
                "verdict": n3_verdict,
            },
        },
        "verdicts": {"N1": n1_verdict, "N2": n2_verdict, "N3": n3_verdict},
        "descriptive": {
            "subset": ("identical paired-eligible subset (≥30 prior "
                       "same-season games) for all three items"),
            "p_home_win_calibration_deciles": calibration(rows),
            "cover_brier_fixed_half_line_grid": cover_grid_out,
            "cover_grid_note": ("Fixed grid declared in spec §5; no "
                                "market lines used. Event: home margin "
                                "+ line > 0."),
            "model_only_all_scored": mo,
        },
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
                  "home_score", "margin", "total", "home_mean",
                  "away_mean", "home_rating", "away_rating",
                  "p_model_home_win", "y_home_win", "clim_prior_n",
                  "paired_eligible", "brier_model", "brier_b1",
                  "logloss_model", "logloss_b1", "crps_margin_model",
                  "crps_margin_b1", "crps_total_model", "crps_total_b2"]
        with open(args.audit, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(audit)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
