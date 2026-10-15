#!/usr/bin/env python3
"""RESEARCH_EVIDENCE — MLB Lane A run line ±1.5 vs closing market (M2).

HARD LABELS (read before citing any number from this script):

* This is a RETROSPECTIVE evaluation on DEVELOPMENT data. It promotes
  NOTHING, changes no production status, and does not touch Lane A
  activation (OFF).
* The closing snapshots in the source dataset are UNTIMESTAMPED. This
  evaluation is in the retrospective-diagnostic evidence class; it does
  NOT satisfy the strict paired contract (PR #2077) and no output may
  be entered as strict-contract validation.
* The market leg is a comparison baseline only. Market prices never
  enter the Lane A leg (market-blind by construction).

Spec: mlb_market_legs_20261014/SPEC_M2_RUNLINE.md
(SHA-256 68c7020fef4df5bb9ab132dcf43b652b4ffcb57cff92e49cde30949e780785b6),
written and hashed before any run-line result on this corpus existed.

Model identity: artifacts/free_models.py at main
2a713380c7d49733577c238a126f487382634040 — Lane A via the module's own
context_for() / score_means() / model_probability("MLB", "SPREAD", ...),
with a corpus-backed provider implementing the PublicContext.schedule()
semantics of the M1 spec §2. Weather neutralized to 0.0 (M1 spec §2b).

Verification precondition (spec §1): the M1 evaluator re-run against
this same pinned tree reproduced M1's published results exactly
(n = 10,237; Brier 0.247856; ΔBrier +0.011523 [+0.007548, +0.016433]) —
filed as mlb_market_legs_20261014/M1_REPRODUCTION_RESULTS.json.

Sealed window: games starting in [2024-07-01, 2024-09-01) UTC are
excluded from BOTH scoring and rating samples (Jul-Aug 2024 bullpen
holdout is SEALED).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import importlib.util
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "free_models_pinned", REPO_ROOT / "artifacts" / "free_models.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

BOOK_PRIORITY = ["draftkings", "fanduel", "caesars", "bet365",
                 "betmgm", "bet_rivers_ny"]
SEALED_START = datetime(2024, 7, 1, tzinfo=timezone.utc)
SEALED_END = datetime(2024, 9, 1, tzinfo=timezone.utc)
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261013
EPS = 1e-15
PARITY_GAMES = 25
EXPECTED_DATASET_SHA256 = \
    "3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b"
SPEC_SHA256 = \
    "68c7020fef4df5bb9ab132dcf43b652b4ffcb57cff92e49cde30949e780785b6"
MAIN_COMMIT = "2a713380c7d49733577c238a126f487382634040"
CLIM_MIN_PRIOR = 30

FRANCHISE_ALIASES = {"Athletics Athletics": "Athletics",
                     "Oakland Athletics": "Athletics"}


def franchise(name):
    return FRANCHISE_ALIASES.get(name, name)


def parse_start(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def in_sealed_window(start):
    return SEALED_START <= start < SEALED_END


class CorpusProvider:
    """Corpus-backed provider with PublicContext.schedule() semantics
    (verbatim from the M1 evaluator)."""

    def __init__(self, samples):
        self.samples = samples

    def fixture(self, sport, away, home, start):
        return start, "MLB"

    def identify(self, sport, name):
        return {"id": franchise(name), "name": name}

    def schedule(self, sport, team, kickoff):
        fid = team["id"]
        completed = [entry for entry in self.samples.get(fid, [])
                     if entry[0] < kickoff and entry[0].year == kickoff.year]
        return sorted(completed, reverse=True)[:5]

    def weather(self, sport, competition, kickoff, latitude=None,
                longitude=None):
        return 0.0, "EVALUATION_NEUTRALIZED_NO_PIT_FORECAST"


def usable_price(v):
    return isinstance(v, (int, float)) and v != 0 and abs(v) >= 100


def implied_prob(american):
    if american < 0:
        return -american / (-american + 100.0)
    return 100.0 / (american + 100.0)


def market_runline(game):
    """(no-vig P(home covers), book, raw_home, raw_away, home_spread)
    or (None, ..., reason). Spec §5 main-line rule: first priority book
    whose pointspread currentLine is a symmetric +/-1.5 with both
    prices usable."""
    entries = (game.get("odds") or {}).get("pointspread") or []
    if not entries:
        return None, None, None, None, None, "NO_POINTSPREAD_ENTRIES"
    by_book = {e.get("sportsbook"): e for e in entries}
    for book in BOOK_PRIORITY:
        entry = by_book.get(book)
        if entry is None:
            continue
        line = entry.get("currentLine") or {}
        hs, aws = line.get("homeSpread"), line.get("awaySpread")
        home, away = line.get("homeOdds"), line.get("awayOdds")
        if (isinstance(hs, (int, float)) and isinstance(aws, (int, float))
                and hs == -aws and abs(hs) == 1.5
                and usable_price(home) and usable_price(away)):
            q_h, q_a = implied_prob(home), implied_prob(away)
            return q_h / (q_h + q_a), book, home, away, hs, None
    return None, None, None, None, None, "NO_MAIN_RUNLINE_CLOSE"


def load_games(path):
    raw_bytes = Path(path).read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest != EXPECTED_DATASET_SHA256:
        raise SystemExit(
            f"DATASET_SHA256_MISMATCH: got {digest}, expected "
            f"{EXPECTED_DATASET_SHA256} — refusing to score a corpus "
            "that is not the manifested one.")
    raw = json.loads(raw_bytes)
    games = []
    for date_key in sorted(raw):
        for g in raw[date_key]:
            gv = g.get("gameView") or {}
            games.append({
                "date_key": date_key,
                "start": parse_start(gv["startDate"]),
                "season": parse_start(gv["startDate"]).year,
                "game_type": gv.get("gameType"),
                "home": (gv.get("homeTeam") or {}).get("fullName"),
                "away": (gv.get("awayTeam") or {}).get("fullName"),
                "home_score": gv.get("homeTeamScore"),
                "away_score": gv.get("awayTeamScore"),
                "raw": g,
            })
    games.sort(key=lambda g: (g["start"], g["away"] or "", g["home"] or ""))
    return games


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


def summarize(rows):
    n = len(rows)
    out = {"n": n}
    if not n:
        return out
    out["brier_model"] = sum(brier(r["p_model"], r["y"]) for r in rows) / n
    out["brier_market"] = sum(brier(r["p_market"], r["y"]) for r in rows) / n
    out["logloss_model"] = sum(logloss(r["p_model"], r["y"]) for r in rows) / n
    out["logloss_market"] = sum(logloss(r["p_market"], r["y"]) for r in rows) / n
    for metric, fn in (("brier", brier), ("logloss", logloss)):
        by_block = defaultdict(list)
        for r in rows:
            by_block[r["week"]].append(fn(r["p_model"], r["y"])
                                       - fn(r["p_market"], r["y"]))
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
                     "observed": sum(r["y"] for r in sel) / len(sel)})
    return bins


def margin_pmf(home_mean, away_mean):
    a, b = fm.poisson(home_mean), fm.poisson(away_mean)
    pmf = defaultdict(float)
    for h, ph in enumerate(a):
        if ph == 0.0:
            continue
        for aw, pa in enumerate(b):
            if pa:
                pmf[h - aw] += ph * pa
    return dict(pmf)


def crps_int(pmf, y):
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
        "MLB", game["away"], game["home"], game["start"], provider, {})
    return fm.score_means("MLB", context)


def calculate_parity_check(provider, game, home_spread, p_pipeline):
    """End-to-end parity: pinned calculate() SPREAD view must agree."""
    now = game["start"] - timedelta(hours=1)
    row = {
        "sport": "MLB", "market": "SPREAD", "side": "HOME",
        "line": home_spread, "odds": -110,
        "away": game["away"], "home": game["home"],
        "commence_time": game["start"].isoformat(),
        "quote_captured_at": (now - timedelta(seconds=60)).isoformat(),
    }
    result = fm.calculate(row, provider, now)
    lanes = result.get("pricing_lanes") or {}
    view = lanes.get("lane_a_independent") or result.get(
        "independent_projection")
    if view is None:
        raise AssertionError(f"calculate() returned no Lane A view: "
                             f"{result.get('status')} {result.get('reason')}")
    diff = abs(view["estimate_p"] - round(p_pipeline, 6))
    if diff > 1.5e-6:
        raise AssertionError(
            f"calculate() Lane A estimate_p {view['estimate_p']} diverges "
            f"from pipeline {p_pipeline} for {game['away']} @ "
            f"{game['home']} {game['start']}")
    if view["push_p"] != 0:
        raise AssertionError("SPREAD at +/-1.5 must carry zero push mass")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default=None, help="results JSON path")
    ap.add_argument("--audit", default=None, help="per-game audit CSV path")
    ap.add_argument("--m1-audit", default=None,
                    help="M1 audit CSV for matched-subset overlap")
    args = ap.parse_args()

    games = load_games(args.dataset)
    counts = Counter()

    samples = defaultdict(list)
    for g in games:
        if g["game_type"] != "R":
            continue
        if g["home_score"] is None or g["away_score"] is None:
            continue
        if in_sealed_window(g["start"]):
            continue
        samples[franchise(g["home"])].append(
            (g["start"], g["home_score"], g["away_score"]))
        samples[franchise(g["away"])].append(
            (g["start"], g["away_score"], g["home_score"]))
    provider = CorpusProvider(samples)

    # Climatology pools: per season, (start, home margin) for population
    # games outside the sealed window, appended in start order.
    clim_starts = defaultdict(list)
    clim_values = defaultdict(list)
    for g in games:
        if g["game_type"] != "R" or in_sealed_window(g["start"]):
            continue
        if g["home_score"] is None or g["away_score"] is None:
            continue
        clim_starts[g["season"]].append(g["start"])
        clim_values[g["season"]].append(g["home_score"] - g["away_score"])

    m1_included = set()
    if args.m1_audit:
        with open(args.m1_audit, newline="") as fh:
            for r in csv.DictReader(fh):
                if r["status"] == "INCLUDED":
                    m1_included.add((r["start"], r["away"], r["home"]))

    rows = []
    audit = []
    crps_rows = []  # {season, crps_model, crps_clim or None}
    parity_done = 0
    overlap = 0
    for g in games:
        counts[f"type_{g['game_type']}"] += 1
        if g["game_type"] != "R":
            continue
        counts["population_R"] += 1
        base = {"start": g["start"].isoformat(), "season": g["season"],
                "away": g["away"], "home": g["home"],
                "away_score": g["away_score"], "home_score": g["home_score"],
                "snapshot_created_at": "NOT_RECORDED_BY_SOURCE",
                "minutes_snapshot_to_first_pitch": "NOT_COMPUTABLE"}
        if in_sealed_window(g["start"]):
            counts["excluded_sealed_window"] += 1
            audit.append({**base, "status": "EXCLUDED",
                          "reason": "SEALED_WINDOW_2024_07_08"})
            continue
        if g["home_score"] is None or g["away_score"] is None:
            counts["excluded_no_score"] += 1
            audit.append({**base, "status": "EXCLUDED",
                          "reason": "NO_FINAL_SCORE"})
            continue
        if g["home_score"] == g["away_score"]:
            counts["excluded_tied_final"] += 1
            audit.append({**base, "status": "EXCLUDED",
                          "reason": "TIED_FINAL_SCORE"})
            continue
        p_market, book, raw_h, raw_a, spread, why = market_runline(g["raw"])
        if p_market is None:
            counts[f"excluded_{why.lower()}"] += 1
            audit.append({**base, "status": "EXCLUDED", "reason": why})
            continue
        home_mean, away_mean = lane_a_means(provider, g)
        p_model, push = fm.model_probability(
            "MLB", "SPREAD", "HOME", spread, home_mean, away_mean)
        if push != 0.0:
            raise AssertionError("push mass at a +/-1.5 line must be 0")
        if parity_done < PARITY_GAMES:
            calculate_parity_check(provider, g, spread, p_model)
            parity_done += 1
        margin = g["home_score"] - g["away_score"]
        y = 1 if margin + spread > 0 else 0
        iso = g["start"].isocalendar()
        rows.append({"p_model": p_model, "p_market": p_market, "y": y,
                     "season": g["season"],
                     "week": f"{iso[0]}-W{iso[1]:02d}", "book": book})
        counts["scored"] += 1
        if (g["start"].isoformat(), g["away"], g["home"]) in m1_included:
            overlap += 1
        # Calibration leg: margin CRPS, model vs climatology.
        c_model = crps_int(margin_pmf(home_mean, away_mean), margin)
        starts = clim_starts[g["season"]]
        idx = bisect.bisect_left(starts, g["start"])
        c_clim = None
        if idx >= CLIM_MIN_PRIOR:
            vals = clim_values[g["season"]][:idx]
            pmf_c = {v: c / idx for v, c in Counter(vals).items()}
            c_clim = crps_int(pmf_c, margin)
        else:
            counts["cal_clim_ineligible_lt30_prior"] += 1
        crps_rows.append({"season": g["season"], "crps_model": c_model,
                          "crps_clim": c_clim})
        audit.append({**base, "status": "INCLUDED", "reason": "",
                      "book": book, "raw_home_odds": raw_h,
                      "raw_away_odds": raw_a, "home_spread": spread,
                      "p_market_home_cover_novig": round(p_market, 6),
                      "p_model_home_cover": round(p_model, 6),
                      "home_mean": round(home_mean, 3),
                      "away_mean": round(away_mean, 3),
                      "y_home_cover": y, "margin": margin,
                      "crps_model": round(c_model, 6),
                      "crps_clim": (round(c_clim, 6)
                                    if c_clim is not None else "")})

    overall = summarize(rows)
    by_season = {}
    for season in sorted({r["season"] for r in rows}):
        by_season[str(season)] = summarize(
            [r for r in rows if r["season"] == season])

    def crps_summary(sub):
        n_all = len(sub)
        paired = [r for r in sub if r["crps_clim"] is not None]
        out = {"n": n_all,
               "crps_model_mean": (sum(r["crps_model"] for r in sub) / n_all
                                   if n_all else None),
               "paired_n": len(paired)}
        if paired:
            out["crps_model_mean_paired"] = (
                sum(r["crps_model"] for r in paired) / len(paired))
            out["crps_clim_mean_paired"] = (
                sum(r["crps_clim"] for r in paired) / len(paired))
            out["crps_diff_model_minus_clim"] = (
                out["crps_model_mean_paired"]
                - out["crps_clim_mean_paired"])
        return out

    cal = {"margin_crps": {"pooled": crps_summary(crps_rows),
                           "by_season": {
                               str(s): crps_summary(
                                   [r for r in crps_rows
                                    if r["season"] == s])
                               for s in sorted({r["season"]
                                                for r in crps_rows})}},
           "cover_prob_calibration_deciles": calibration(rows),
           "model_only": {
               "brier": overall.get("brier_model"),
               "logloss": overall.get("logloss_model")}}

    incl = [a for a in audit if a["status"] == "INCLUDED"]
    excl = [a for a in audit if a["status"] == "EXCLUDED"]

    def home_win_rate(sub):
        scored = [a for a in sub if a["home_score"] is not None
                  and a["away_score"] is not None]
        if not scored:
            return None
        return sum(1 for a in scored
                   if a["home_score"] > a["away_score"]) / len(scored)

    bias = {"included_n": len(incl),
            "included_home_win_rate": home_win_rate(incl),
            "excluded_n": len(excl),
            "excluded_home_win_rate": home_win_rate(excl),
            "excluded_by_reason": dict(Counter(a["reason"] for a in excl))}

    db = overall.get("paired_brier_diff") or {}
    dl = overall.get("paired_logloss_diff") or {}
    full_seasons_ok = all(
        by_season.get(str(s), {}).get("n", 0) >= 200
        for s in (2021, 2022, 2023, 2024))
    if overall["n"] < 1000 or not full_seasons_ok:
        verdict = "INCONCLUSIVE_BY_COVERAGE"
    elif (db.get("ci95_hi", 0) < 0) and (dl.get("ci95_hi", 0) < 0):
        verdict = "BEATS_MARKET"
    else:
        verdict = "DOES_NOT_BEAT_MARKET"

    results = {
        "item": "M2_RUN_LINE_MARKET_LEG",
        "label": "RESEARCH_EVIDENCE_RETROSPECTIVE_NOT_VALIDATION",
        "evidence_class": ("RETROSPECTIVE_DIAGNOSTIC — closing snapshots "
                           "are untimestamped; does NOT satisfy the "
                           "PR #2077 strict paired contract."),
        "contract_note": ("Promotes nothing. Lane A activation stays OFF; "
                          "promotion requires LANE_A_ML_PAIRED_DESIGN_V1 "
                          "forward paired evidence under activation."),
        "spec_sha256": SPEC_SHA256,
        "model_identity": {
            "file": "artifacts/free_models.py",
            "main_commit": MAIN_COMMIT,
            "path": ("calculate() Lane A via context_for + score_means + "
                     "model_probability(MLB, SPREAD)"),
            "weather": "NEUTRALIZED_0.0_NO_PIT_FORECAST (M1 spec §2b)",
            "m1_reproduction_on_pin": (
                "PASSED — M1 evaluator on this tree reproduced M1 exactly "
                "(n=10237, Brier 0.247856, dBrier +0.011523 "
                "[+0.007548, +0.016433]); see M1_REPRODUCTION_RESULTS.json"),
        },
        "dataset": {
            "file": "mlb_odds_dataset.json",
            "sha256": EXPECTED_DATASET_SHA256,
            "in_repo": False,
            "manifest": "mlb_market_legs_20261014/DATASET_MANIFEST.md",
            "games_total": len(games),
        },
        "counts": dict(counts),
        "book_usage": dict(Counter(r["book"] for r in rows)),
        "spread_orientation": dict(Counter(
            "HOME_-1.5" if a.get("home_spread") == -1.5 else "HOME_+1.5"
            for a in incl)),
        "parity_checks_passed": parity_done,
        "overall": overall,
        "by_season": by_season,
        "calibration_leg_descriptive": cal,
        "overlap_with_m1_ml_subset": overlap if args.m1_audit else None,
        "missing_game_bias_audit": bias,
        "verdict": verdict,
        "bootstrap": {"blocks": "ISO calendar weeks",
                      "resamples": BOOTSTRAP_RESAMPLES,
                      "seed": BOOTSTRAP_SEED},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    text = json.dumps(results, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    if args.audit:
        fields = ["start", "season", "away", "home", "away_score",
                  "home_score", "status", "reason", "book", "raw_home_odds",
                  "raw_away_odds", "home_spread",
                  "p_market_home_cover_novig", "p_model_home_cover",
                  "home_mean", "away_mean", "y_home_cover", "margin",
                  "crps_model", "crps_clim",
                  "snapshot_created_at", "minutes_snapshot_to_first_pitch"]
        with open(args.audit, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(audit)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
