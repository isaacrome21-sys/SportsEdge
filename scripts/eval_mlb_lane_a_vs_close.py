#!/usr/bin/env python3
"""RESEARCH_EVIDENCE — MLB Lane A (independent) vs closing market, walk-forward.

HARD LABELS (read before citing any number from this script):

* This is a RETROSPECTIVE evaluation on DEVELOPMENT data. It promotes
  NOTHING, changes no production status, and does not touch Lane A
  activation (OFF). Lane A promotion still requires the forward paired
  design LANE_A_ML_PAIRED_DESIGN_V1 under an owner activation ruling.
* The closing snapshots in the source dataset are UNTIMESTAMPED. This
  evaluation therefore does NOT satisfy the strict paired contract
  (PR #2077) and no output may be entered as strict-contract validation.
* The market leg is a comparison baseline only. Market prices never enter
  the Lane A leg (market-blind by construction).

Spec: ~/workspace/sportsedge/mlb_lane_a_evaluation_20261013/SPEC.md
(SHA-256 72ee1e24b14e36b32cc3c1f3acd8592a5ad10e456f3d73ef02ae53e40a2e0f1c),
written before any Lane A result on this corpus was computed.

Model identity: artifacts/free_models.py at main
655715907d101052bfc7cb3357f1442db82d8d8b — calculate()'s Lane A path,
executed through the module's own context_for() / score_means() /
model_probability() with a corpus-backed provider implementing the
PublicContext.schedule() semantics declared in the spec §2. The only
non-PIT live input (the real-time weather forecast heuristic) is
neutralized to 0.0 per spec §2(b).

Sealed window: games starting in [2024-07-01, 2024-09-01) UTC are
excluded from BOTH scoring and rating samples (Jul-Aug 2024 bullpen
holdout is SEALED).
"""
from __future__ import annotations

import argparse
import csv
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

FRANCHISE_ALIASES = {"Athletics Athletics": "Athletics",
                     "Oakland Athletics": "Athletics"}


def franchise(name):
    return FRANCHISE_ALIASES.get(name, name)


def parse_start(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def in_sealed_window(start):
    return SEALED_START <= start < SEALED_END


class CorpusProvider:
    """Corpus-backed provider with PublicContext.schedule() semantics.

    samples: franchise -> list of (start, pf, pa) for every regular-season
    game in the corpus OUTSIDE the sealed window, with final scores.
    """

    def __init__(self, samples):
        self.samples = samples

    def fixture(self, sport, away, home, start):
        # Spec §2(c): the corpus record itself is the fixture.
        return start, "MLB"

    def identify(self, sport, name):
        return {"id": franchise(name), "name": name}

    def schedule(self, sport, team, kickoff):
        # Mirror PublicContext.schedule(): same-season completed games
        # strictly before kickoff, tuple-sorted descending, first 5.
        fid = team["id"]
        completed = [entry for entry in self.samples.get(fid, [])
                     if entry[0] < kickoff and entry[0].year == kickoff.year]
        return sorted(completed, reverse=True)[:5]

    def weather(self, sport, competition, kickoff, latitude=None,
                longitude=None):
        # Spec §2(b): neutralized — no PIT forecast exists for 2021-2025.
        return 0.0, "EVALUATION_NEUTRALIZED_NO_PIT_FORECAST"


def usable_price(v):
    return isinstance(v, (int, float)) and v != 0 and abs(v) >= 100


def implied_prob(american):
    if american < 0:
        return -american / (-american + 100.0)
    return 100.0 / (american + 100.0)


def market_home_prob(game):
    """(no-vig P(home), book, raw_home, raw_away) or (None, None, why)."""
    entries = (game.get("odds") or {}).get("moneyline") or []
    if not entries:
        return None, None, None, None, "NO_ML_ENTRIES"
    by_book = {e.get("sportsbook"): e for e in entries}
    for book in BOOK_PRIORITY:
        entry = by_book.get(book)
        if entry is None:
            continue
        line = entry.get("currentLine") or {}
        home, away = line.get("homeOdds"), line.get("awayOdds")
        if usable_price(home) and usable_price(away):
            p_h, p_a = implied_prob(home), implied_prob(away)
            return p_h / (p_h + p_a), book, home, away, None
    return None, None, None, None, "NO_USABLE_CLOSING_ML"


def load_games(path):
    raw = json.loads(Path(path).read_text())
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


def lane_a_home_prob(provider, game):
    """Lane A P(home win) via the pinned module's own functions."""
    context, _kickoff, _notes = fm.context_for(
        "MLB", game["away"], game["home"], game["start"], provider, {})
    home_mean, away_mean = fm.score_means("MLB", context)
    win, _push = fm.model_probability(
        "MLB", "ML", "HOME", None, home_mean, away_mean)
    return win, home_mean, away_mean


def calculate_parity_check(provider, game, p_pipeline):
    """End-to-end parity: pinned calculate() must agree with the pipeline."""
    now = game["start"] - timedelta(hours=1)
    row = {
        "sport": "MLB", "market": "ML", "side": "HOME", "odds": -110,
        "away": game["away"], "home": game["home"],
        "commence_time": game["start"].isoformat(),
        "quote_captured_at": (now - timedelta(seconds=60)).isoformat(),
    }
    result = fm.calculate(row, provider, now)
    view = None
    lanes = result.get("pricing_lanes") or {}
    if lanes.get("lane_a_independent"):
        view = lanes["lane_a_independent"]
    elif result.get("independent_projection"):
        view = result["independent_projection"]
    if view is None:
        raise AssertionError(f"calculate() returned no Lane A view: "
                             f"{result.get('status')} {result.get('reason')}")
    diff = abs(view["estimate_p"] - round(p_pipeline, 6))
    if diff > 1.5e-6:
        raise AssertionError(
            f"calculate() Lane A estimate_p {view['estimate_p']} diverges "
            f"from pipeline {p_pipeline} for {game['away']} @ {game['home']} "
            f"{game['start']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default=None, help="results JSON path")
    ap.add_argument("--audit", default=None, help="per-game audit CSV path")
    args = ap.parse_args()

    games = load_games(args.dataset)
    counts = Counter()

    # Rating samples: regular-season games outside the sealed window.
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

    rows = []
    audit = []
    parity_done = 0
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
        p_market, book, raw_h, raw_a, why = market_home_prob(g["raw"])
        if p_market is None:
            counts[f"excluded_{why.lower()}"] += 1
            audit.append({**base, "status": "EXCLUDED", "reason": why})
            continue
        p_model, home_mean, away_mean = lane_a_home_prob(provider, g)
        if parity_done < PARITY_GAMES:
            calculate_parity_check(provider, g, p_model)
            parity_done += 1
        y = 1 if g["home_score"] > g["away_score"] else 0
        iso = g["start"].isocalendar()
        rows.append({"p_model": p_model, "p_market": p_market, "y": y,
                     "season": g["season"],
                     "week": f"{iso[0]}-W{iso[1]:02d}", "book": book})
        counts["scored"] += 1
        audit.append({**base, "status": "INCLUDED", "reason": "",
                      "book": book, "raw_home_odds": raw_h,
                      "raw_away_odds": raw_a,
                      "p_market_home_novig": round(p_market, 6),
                      "p_model_home": round(p_model, 6),
                      "home_mean": round(home_mean, 3),
                      "away_mean": round(away_mean, 3), "y_home_win": y})

    overall = summarize(rows)
    by_season = {}
    for season in sorted({r["season"] for r in rows}):
        by_season[str(season)] = summarize(
            [r for r in rows if r["season"] == season])

    incl = [a for a in audit if a["status"] == "INCLUDED"]
    excl = [a for a in audit if a["status"] == "EXCLUDED"]
    def home_win_rate(sub):
        scored = [a for a in sub if a["home_score"] is not None
                  and a["away_score"] is not None]
        if not scored:
            return None
        return sum(1 for a in scored
                   if a["home_score"] > a["away_score"]) / len(scored)
    bias = {"included_n": len(incl), "included_home_win_rate": home_win_rate(incl),
            "excluded_n": len(excl), "excluded_home_win_rate": home_win_rate(excl),
            "excluded_by_reason": dict(Counter(a["reason"] for a in excl))}

    # Predeclared gate (spec §7).
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
        "label": "RESEARCH_EVIDENCE_RETROSPECTIVE_NOT_VALIDATION",
        "contract_note": ("Closing snapshots are untimestamped; this does "
                          "NOT satisfy the PR #2077 strict paired contract "
                          "and promotes nothing. Lane A activation stays "
                          "OFF; promotion requires LANE_A_ML_PAIRED_DESIGN_V1 "
                          "forward paired evidence under activation."),
        "spec_sha256": "72ee1e24b14e36b32cc3c1f3acd8592a5ad10e456f3d73ef02ae53e40a2e0f1c",
        "model_identity": {
            "file": "artifacts/free_models.py",
            "main_commit": "655715907d101052bfc7cb3357f1442db82d8d8b",
            "path": "calculate() Lane A via context_for + score_means + model_probability",
            "weather": "NEUTRALIZED_0.0_NO_PIT_FORECAST (spec §2b)",
        },
        "dataset": {
            "file": "mlb_odds_dataset.json",
            "sha256": "3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b",
            "games_total": len(games),
        },
        "counts": dict(counts),
        "book_usage": dict(Counter(r["book"] for r in rows)),
        "parity_checks_passed": parity_done,
        "overall": overall,
        "by_season": by_season,
        "calibration_model_deciles": calibration(rows),
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
                  "raw_away_odds", "p_market_home_novig", "p_model_home",
                  "home_mean", "away_mean", "y_home_win",
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
