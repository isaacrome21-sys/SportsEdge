"""EITHER_PITCHER shrunk-marginals evaluator (PREREG_EITHER_PITCHER_SHRUNK_MARGINALS + Amendment 1).

RESEARCH_EVIDENCE, calibration only. Not a market verdict, not a promotion input.

Run order (enforced):
  1. prereg SHA-256 must equal SPEC_HASHES.txt, else refuse.
  2. pinned engine blob must equal 00cba6f6..., else refuse.
  3. FROZEN-arm reproduction on 2024 design pairs vs M31's published per-season
     signed error (Amendment 1 sec. 2): max |diff| must be < 1e-9, else StopRun.
  4. Only then is 2026 scored.

Usage:
  python eval_either_pitcher_shrunk.py --m31-worktree WT --bundles DIR --out OUT.json
WT is a checkout of research/mlb-market-legs-20261014 (M31 evaluator + engine).
DIR holds pitching_gamelogs_{2024,2025,2026}.gz from staging run 39026089063.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PREREG = HERE / "PREREG_EITHER_PITCHER_SHRUNK_MARGINALS.md"
SPEC_HASHES = HERE / "SPEC_HASHES.txt"
EXPECTED_ENGINE_BLOB = "00cba6f664e313b53ab0084e6f3f471a9d85b566"
K = 10
SEED = 20261017
RESAMPLES = 2000
TAIL_MATERIAL = 0.02
TEST_SEASON = 2026


class StopRun(RuntimeError):
    pass


def sha256_file(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check_prereg():
    want = SPEC_HASHES.read_text().split()[0]
    got = sha256_file(PREREG)
    if got != want:
        raise StopRun(f"prereg hash mismatch {got} != {want}")
    return got


def load_m31(wt: Path):
    blob = subprocess.check_output(
        ["git", "-C", str(wt), "hash-object", "sportsedge/pitcher_joint_engine.py"], text=True).strip()
    if blob != EXPECTED_ENGINE_BLOB:
        raise StopRun(f"engine blob {blob} != {EXPECTED_ENGINE_BLOB}")
    sys.path.insert(0, str(wt))
    spec = importlib.util.spec_from_file_location("m31", wt / "scripts/eval_mlb_either_dependence.py")
    m31 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m31)
    return m31, blob


def load_bundle(path: Path) -> dict:
    out = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            r = json.loads(line)
            if hashlib.sha256(r["body"].encode()).hexdigest() != r["sha256"]:
                raise StopRun(f"record sha mismatch in {path}: {r['url']}")
            pid = int(r["url"].split("/people/")[1].split("/")[0])
            out[pid] = json.loads(r["body"])
    return out


# ------------------------------------------------------------- population
def build_season(m31, payloads: dict, season: int) -> dict:
    """M31.build_population for one season, verbatim logic, plus the
    uncapped all-prior pool (CHALLENGER/B1) per fixture."""
    by_pitcher, sides = {}, {}
    for pid in sorted(payloads):
        starts = m31.parse_starts(payloads[pid])
        if starts:
            by_pitcher[pid] = m31.production_order(starts)
        sides[pid] = m31.parse_sides(payloads[pid])
    fixtures, exclusions, cand = [], Counter(), 0
    for pid, desc in by_pitcher.items():
        for s in desc:
            if s["game_type"] != "R":
                continue
            cand += 1
            d = s["date"]
            if m31.sealed(d):
                exclusions["SEALED_WINDOW"] += 1
                continue
            pool = m31.engine_pool(desc, d)
            if len(pool) < 5:
                exclusions["POOL_STARTS_LT_5"] += 1
                continue
            fixtures.append({"pitcher_id": pid, "date": d, "game_pk": s["game_pk"], "season": season,
                             "outcome": s["stats"], "pool": pool,
                             "all_prior": [r["stats"] for r in m31.all_prior(desc, d)],
                             "is_home": sides[pid].get(s["game_pk"])})
    fixtures.sort(key=lambda x: (x["date"], x["pitcher_id"], x["game_pk"]))
    # league rows: every parsed start of every pitcher this season (date-keyed), sealed removed
    league = sorted(((s["date"], s["stats"]) for desc in by_pitcher.values() for s in desc
                     if not m31.sealed(s["date"])), key=lambda t: t[0])
    return {"fixtures": fixtures, "exclusions": dict(exclusions), "candidate_regular_starts": cand,
            "league": league}


def pairs_for(m31, season: int, built: dict):
    # assemble_pairs iterates (2024, 2025); run it on a population holding only this season
    pop = {"seasons": {2024: built if season == 2024 else {"fixtures": []},
                       2025: built if season != 2024 else {"fixtures": []}}}
    pairs, counts = m31.assemble_pairs(pop)
    for p in pairs:
        p["season"] = season
        p["block"] = f"{season}-{p['date'].isocalendar()[0]}W{p['date'].isocalendar()[1]:02d}"
    c = counts["2024" if season == 2024 else "2025"]
    return pairs, c


class League:
    def __init__(self, rows, field, vmax):
        self.dates = [d for d, _ in rows]
        self.vmax = vmax
        cum = np.zeros((len(rows) + 1, vmax + 1))
        for i, (_, st) in enumerate(rows):
            cum[i + 1] = cum[i]
            cum[i + 1, min(int(st[field]), vmax)] += 1
        self.cum = cum

    def dist(self, d):
        i = bisect_left(self.dates, d)  # strictly prior dates
        c = self.cum[i]
        if c.sum() == 0:
            raise StopRun(f"empty league distribution at {d}")
        return c / c.sum()


def pool_counts(rows, field, vmax):
    c = np.zeros(vmax + 1)
    for st in rows:
        c[min(int(st[field]), vmax)] += 1
    return c


def tail(p, X):  # P(v >= X)
    return float(p[X:].sum())


def head(p, N):  # P(v <= N)
    return float(p[:N + 1].sum())


def either(pa, pb, form, T):
    if form == "XPLUS":
        return 1.0 - (1.0 - tail(pa, T)) * (1.0 - tail(pb, T))
    return 1.0 - (1.0 - head(pa, T)) * (1.0 - head(pb, T))


def realized(va, vb, form, T):
    return float((va >= T or vb >= T) if form == "XPLUS" else (va <= T or vb <= T))


def score(m31, pairs, leagues, frozen_tracker):
    """Return rows: one per (pair, stat, form, rung) with all four arm probs."""
    rows = []
    for p in pairs:
        for stat, cfg in m31.STATS.items():
            f, vmax = cfg["field"], 60
            L = leagues[stat].dist(p["date"])
            marg = {}
            for side in ("a", "b"):
                c = pool_counts(p[side]["all_prior"], f, vmax)
                n = c.sum()
                marg[side] = {"CHALLENGER": (c + K * L) / (n + K), "B1": c / n, "B2": L}
            va, vb = p["a"]["outcome"][f], p["b"]["outcome"][f]
            for form, grid, eside, mk in (("XPLUS", cfg["xplus"], "OVER", lambda X: X - 0.5),
                                          ("ORFEWER", cfg["orfewer"], "UNDER", lambda N: N + 0.5)):
                for T in grid:
                    rows.append({
                        "block": p["block"], "game_pk": p["game_pk"], "stat": stat, "form": form, "T": T,
                        "y": realized(va, vb, form, T),
                        "FROZEN": m31.either_prob(p["a"]["pool"], p["b"]["pool"], stat, eside, mk(T),
                                                  tracker=frozen_tracker),
                        "CHALLENGER": either(marg["a"]["CHALLENGER"], marg["b"]["CHALLENGER"], form, T),
                        "B1": either(marg["a"]["B1"], marg["b"]["B1"], form, T),
                        "B2": either(marg["a"]["B2"], marg["b"]["B2"], form, T),
                    })
    return rows


def boot(m31, vals, blocks):
    return m31.block_bootstrap_mean_ci(np.asarray(vals), blocks, seed=SEED, resamples=RESAMPLES)


ARMS = ("FROZEN", "CHALLENGER", "B1", "B2")


def summarize(m31, rows, gate: bool):
    out = {}
    for stat in m31.STATS:
        R = [r for r in rows if r["stat"] == stat]
        blocks = [r["block"] for r in R]
        y = np.array([r["y"] for r in R])
        brier = {a: (np.array([r[a] for r in R]) - y) ** 2 for a in ARMS}
        res = {"n_cells_rows": len(R),
               "brier": {a: float(brier[a].mean()) for a in ARMS},
               "delta_challenger_minus": {a: boot(m31, brier["CHALLENGER"] - brier[a], blocks)
                                          for a in ("FROZEN", "B1", "B2")},
               "cells": {}}
        for form in ("XPLUS", "ORFEWER"):
            for T in sorted({r["T"] for r in R if r["form"] == form}):
                C = [r for r in R if r["form"] == form and r["T"] == T]
                cb = [r["block"] for r in C]
                cy = np.array([r["y"] for r in C])
                res["cells"][f"{form}:{T}"] = {
                    "n": len(C), "realized": float(cy.mean()),
                    "mean_predicted": {a: float(np.mean([r[a] for r in C])) for a in ARMS},
                    "signed_error_challenger": boot(m31, np.array([r["CHALLENGER"] for r in C]) - cy, cb),
                    "signed_error_frozen": boot(m31, np.array([r["FROZEN"] for r in C]) - cy, cb),
                }
        if gate:
            leg1 = {a: res["delta_challenger_minus"][a]["ci95_hi"] < 0 for a in ("FROZEN", "B1", "B2")}
            tail_bad = [k for k, v in res["cells"].items()
                        if k.startswith("XPLUS") and v["signed_error_challenger"]["ci95_lo"] > TAIL_MATERIAL]
            if not all(leg1.values()):
                verdict = "DOES_NOT_BEAT_BASELINE"
            elif tail_bad:
                verdict = "MATERIAL_TAIL_OVERSTATEMENT"
            else:
                verdict = "CALIBRATION_PASS"
            res["gate"] = {"leg1_ci_below_zero": leg1, "tail_material_cells": tail_bad, "verdict": verdict}
        out[stat] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--m31-worktree", required=True, type=Path)
    ap.add_argument("--bundles", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    prereg_sha = check_prereg()
    m31, blob = load_m31(a.m31_worktree)
    published = json.loads((a.m31_worktree / "mlb_market_legs_20261014/results_m31_either_dependence.json").read_text())
    bundle_sha = {s: sha256_file(a.bundles / f"pitching_gamelogs_{s}.gz") for s in (2024, 2025, 2026)}

    # ---- step 3: FROZEN reproduction on 2024 (must pass before 2026)
    b24 = build_season(m31, load_bundle(a.bundles / "pitching_gamelogs_2024.gz"), 2024)
    p24, c24 = pairs_for(m31, 2024, b24)
    if c24["pairs_scored"] != 765:
        raise StopRun(f"2024 pairs {c24['pairs_scored']} != 765")
    worst = 0.0
    for stat, cfg in m31.STATS.items():
        for form, grid, side, mk in (("XPLUS", cfg["xplus"], "OVER", lambda X: X - 0.5),
                                     ("ORFEWER", cfg["orfewer"], "UNDER", lambda N: N + 0.5)):
            for T in grid:
                e = [m31.either_prob(p["a"]["pool"], p["b"]["pool"], stat, side, mk(T))
                     - realized(p["a"]["outcome"][cfg["field"]], p["b"]["outcome"][cfg["field"]], form, T)
                     for p in p24]
                pub = published["stats"][stat]["forms"][form]["thresholds"][str(T)]["per_season_mean_signed_error"]["2024"]
                worst = max(worst, abs(float(np.mean(e)) - pub))
    if worst >= 1e-9:
        raise StopRun(f"FROZEN reproduction failed: max |diff| {worst}")

    # ---- design (descriptive) 2024 + 2025
    b25 = build_season(m31, load_bundle(a.bundles / "pitching_gamelogs_2025.gz"), 2025)
    p25, c25 = pairs_for(m31, 2025, b25)
    design = {}
    for s, b, p in ((2024, b24, p24), (2025, b25, p25)):
        lg = {st: League(b["league"], cfg["field"], 60) for st, cfg in m31.STATS.items()}
        design[str(s)] = summarize(m31, score(m31, p, lg, []), gate=False)

    # ---- test 2026
    b26 = build_season(m31, load_bundle(a.bundles / "pitching_gamelogs_2026.gz"), 2026)
    p26, c26 = pairs_for(m31, 2026, b26)
    lg26 = {st: League(b26["league"], cfg["field"], 60) for st, cfg in m31.STATS.items()}
    tracker = []
    rows = score(m31, p26, lg26, tracker)
    test = summarize(m31, rows, gate=True)
    rows_path = a.out.with_name(a.out.stem + "_rows2026.jsonl.gz")
    with open(rows_path, "wb") as fh, gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0) as g:
        for r in rows:
            g.write((json.dumps(r, sort_keys=True) + "\n").encode())

    out = {
        "label": "RESEARCH_EVIDENCE (calibration only; not a market verdict; gate EITHER_PITCHER_MARGINAL_TAIL_ERROR stays)",
        "prereg_sha256": prereg_sha, "engine_blob": blob, "K": K, "seed": SEED, "resamples": RESAMPLES,
        "bundle_sha256": bundle_sha,
        "frozen_reproduction_2024_max_abs_diff": worst,
        "population": {
            str(s): {"candidate_regular_starts": b["candidate_regular_starts"], "fixtures": len(b["fixtures"]),
                     "exclusions": b["exclusions"], "pairs": c}
            for s, b, c in ((2024, b24, c24), (2025, b25, c25), (2026, b26, c26))},
        "frozen_ulp_dispositions_2026": len(tracker),
        "test_2026": test,
        "design_descriptive": design,
        "verdicts_2026": {st: test[st]["gate"]["verdict"] for st in test},
    }
    a.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps(out["verdicts_2026"]), json.dumps(out["population"]["2026"]))
    for st in test:
        print(st, test[st]["brier"], {k: (round(v["mean"], 5), round(v["ci95_lo"], 5), round(v["ci95_hi"], 5))
                                       for k, v in test[st]["delta_challenger_minus"].items()},
              test[st]["gate"]["tail_material_cells"])


if __name__ == "__main__":
    main()
