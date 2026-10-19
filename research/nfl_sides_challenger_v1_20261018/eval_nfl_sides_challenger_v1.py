"""NFL sides challenger v1 evaluator (PREREG_NFL_SIDES_CHALLENGER_V1.md).

SCREEN only — second attempt on used 2018-2025 closing data (see prereg §0/§8).
Refuses to run unless the prereg hash and the pinned corpus hash match.

Usage: python eval_nfl_sides_challenger_v1.py --games games.csv --out results.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CORPUS_SHA = "a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284"

# Challenger constants (prereg §2)
C_START, C_REGRESS, C_HFA, C_K = 1500.0, 1 / 3, 48.0, 20.0
C_STREAM = (1999, 2025)
FIT_SEASONS = (2010, 2017)
# Elo v1 constants (its frozen prereg; recomputed arm, §3)
V1_START, V1_HFA, V1_K = 1505.0, 48.0, 20.0
V1_STREAM = (2015, 2025)
# Scoring (prereg §4/§5)
SCORED_SEASONS = (2018, 2025)
SEED, RESAMPLES = 20261018, 2000


def check_inputs(games_path: Path) -> str:
    want = (HERE / "SPEC_HASHES.txt").read_text().split()[0]
    got = hashlib.sha256((HERE / "PREREG_NFL_SIDES_CHALLENGER_V1.md").read_bytes()).hexdigest()
    if got != want:
        raise SystemExit(f"prereg hash mismatch {got}")
    c = hashlib.sha256(games_path.read_bytes()).hexdigest()
    if c != CORPUS_SHA:
        raise SystemExit(f"corpus hash mismatch {c}")
    return got


def american_to_prob(a: float) -> float:
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def devig_home(home_price: float, away_price: float) -> float:
    pa, pb = american_to_prob(home_price), american_to_prob(away_price)
    return pa / (pa + pb)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(path: Path, lo: int, hi: int) -> list[dict]:
    rows = []
    for r in csv.DictReader(open(path)):
        s = int(r["season"])
        if s < lo or s > hi or r["home_score"] == "" or r["away_score"] == "":
            continue
        rows.append(r)
    rows.sort(key=lambda r: (r["gameday"], r["gametime"] or "00:00", r["game_id"]))
    return rows


def run_engine(rows: list[dict], start: float) -> dict[str, dict]:
    """MOV-Elo stream with the Elo v1 evaluator's batching semantics.

    Returns per-game pregame records keyed by game_id: d (incl. HFA), margin,
    and the raw logistic400 win probability (the update expectation).
    """
    elo: dict[str, float] = defaultdict(lambda: start)
    season = None
    out: dict[str, dict] = {}
    i = 0
    while i < len(rows):
        key = (rows[i]["gameday"], rows[i]["gametime"])
        j = i
        while j < len(rows) and (rows[j]["gameday"], rows[j]["gametime"]) == key:
            j += 1
        batch = rows[i:j]
        s = int(batch[0]["season"])
        if season is not None and s != season:
            for t in list(elo):
                elo[t] = elo[t] + (1 / 3) * (start - elo[t])
        season = s
        updates = []
        for r in batch:
            h, a = r["home_team"], r["away_team"]
            hfa = 0.0 if r["location"] == "Neutral" else C_HFA
            d = elo[h] + hfa - elo[a]
            p_home = 1.0 / (1.0 + 10 ** (-d / 400.0))
            margin = float(r["home_score"]) - float(r["away_score"])
            out[r["game_id"]] = {
                "game_id": r["game_id"], "season": s, "week": int(r["week"]),
                "game_type": r["game_type"], "home": h, "away": a, "d": d,
                "p_home_raw": p_home, "margin": margin,
                "spread_line": num(r["spread_line"]),
                "ml": (num(r["home_moneyline"]), num(r["away_moneyline"])),
            }
            if margin == 0:
                res, mult = 0.5, 1.0
            else:
                res = 1.0 if margin > 0 else 0.0
                winner_diff = d if margin > 0 else -d
                mult = math.log(abs(margin) + 1) * 2.2 / (0.001 * winner_diff + 2.2)
            shift = C_K * mult * (res - p_home)
            updates.append((h, a, shift))
        for h, a, shift in updates:
            elo[h] += shift
            elo[a] -= shift
        i = j
    return out


def fit_calibration(recs: list[dict]) -> dict:
    """Prereg §2 calibration: fit on 2010-2017 pregame d only, then frozen."""
    fit = [r for r in recs if FIT_SEASONS[0] <= r["season"] <= FIT_SEASONS[1]]
    d = np.array([r["d"] for r in fit], float)
    m = np.array([r["margin"] for r in fit], float)
    # OLS margin = a + b*d
    b = float(np.cov(d, m, ddof=0)[0, 1] / np.var(d))
    a = float(m.mean() - b * d.mean())
    # Logistic regression home_win ~ d (ties excluded), unregularized MLE, Newton.
    lf = [r for r in fit if r["margin"] != 0]
    dl = np.array([r["d"] for r in lf], float)
    y = np.array([1.0 if r["margin"] > 0 else 0.0 for r in lf], float)
    X = np.column_stack([np.ones_like(dl), dl])
    beta = np.zeros(2)
    for _ in range(200):
        eta = X @ beta
        p = 1.0 / (1.0 + np.exp(-eta))
        w = np.maximum(p * (1.0 - p), 1e-12)
        grad = X.T @ (y - p)
        hess = (X * w[:, None]).T @ X
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-12:
            break
    return {"a": a, "b": b, "alpha": float(beta[0]), "beta": float(beta[1]),
            "fit_n": len(fit), "fit_n_logistic": len(lf)}


def ll(p: float, y: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def boot(vals, blocks, seed=SEED):
    vals = np.asarray(vals, float)
    keys = sorted(set(blocks))
    idx = {k: n for n, k in enumerate(keys)}
    bi = np.array([idx[b] for b in blocks])
    sums, cnts = np.zeros(len(keys)), np.zeros(len(keys))
    np.add.at(sums, bi, vals)
    np.add.at(cnts, bi, 1)
    rng = np.random.default_rng(seed)
    s = rng.integers(0, len(keys), size=(RESAMPLES, len(keys)))
    m = sums[s].sum(1) / cnts[s].sum(1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return {"mean": float(vals.mean()), "ci95_lo": float(lo), "ci95_hi": float(hi),
            "n": int(len(vals)), "n_blocks": len(keys)}


def evaluate(chall: dict[str, dict], v1: dict[str, dict], coef: dict) -> dict:
    rows = []
    for gid, g in chall.items():
        if not (SCORED_SEASONS[0] <= g["season"] <= SCORED_SEASONS[1]):
            continue
        if g["game_type"] != "REG":
            continue
        h, a = g["ml"]
        if h is None or a is None or g["margin"] == 0:
            continue
        y = 1.0 if g["margin"] > 0 else 0.0
        pc = 1.0 / (1.0 + math.exp(-(coef["alpha"] + coef["beta"] * g["d"])))
        rows.append({
            "game_id": gid, "block": f"{g['season']}-W{g['week']:02d}", "y": y,
            "pc": pc, "pm": devig_home(h, a), "pv1": v1[gid]["p_home_raw"],
            "pred_margin": coef["a"] + coef["b"] * g["d"],
            "spread_line": g["spread_line"], "margin": g["margin"],
        })
    blocks = [r["block"] for r in rows]
    llc = [ll(r["pc"], r["y"]) for r in rows]
    llm = [ll(r["pm"], r["y"]) for r in rows]
    llv = [ll(r["pv1"], r["y"]) for r in rows]
    d_cm = [x - y for x, y in zip(llc, llm)]
    d_cv = [x - y for x, y in zip(llc, llv)]
    d_vm = [x - y for x, y in zip(llv, llm)]
    res = {
        "n": len(rows),
        "logloss": {"CHALLENGER": float(np.mean(llc)), "MARKET": float(np.mean(llm)),
                    "ELO_V1": float(np.mean(llv))},
        "delta_challenger_minus_market": boot(d_cm, blocks),
        "delta_challenger_minus_elo_v1": boot(d_cv, blocks),
        "delta_elo_v1_minus_market_descriptive": boot(d_vm, blocks),
    }
    res["verdict_vs_close"] = ("BEATS_CLOSE" if res["delta_challenger_minus_market"]["ci95_hi"] < 0
                               else "DOES_NOT_BEAT_CLOSE")
    res["verdict_vs_elo_v1"] = ("BEATS_ELO_V1" if res["delta_challenger_minus_elo_v1"]["ci95_hi"] < 0
                                else "DOES_NOT_BEAT_ELO_V1")
    # Prereg §6 ATS readout + favorite/underdog diagnostic (descriptive, no gate)
    cand = [r for r in rows if r["spread_line"] is not None
            and abs(r["pred_margin"] - r["spread_line"]) > 3]
    decided, covers, pushes = 0, 0, 0
    fav_rows, dog_rows, pickem = [], [], 0
    for r in cand:
        side_home = (r["pred_margin"] - r["spread_line"]) > 3
        if r["margin"] == r["spread_line"]:
            pushes += 1
        else:
            decided += 1
            home_covered = r["margin"] > r["spread_line"]
            if home_covered == side_home:
                covers += 1
        if r["spread_line"] == 0:
            pickem += 1
        else:
            home_fav = r["spread_line"] > 0
            (fav_rows if side_home == home_fav else dog_rows).append(r)
    def subset_stats(rs):
        if not rs:
            return None
        d = [ll(r["pc"], r["y"]) - ll(r["pm"], r["y"]) for r in rs]
        return {"n": len(rs),
                "challenger_logloss": float(np.mean([ll(r["pc"], r["y"]) for r in rs])),
                "delta_challenger_minus_market": boot(d, [r["block"] for r in rs])}
    non_pickem = len(fav_rows) + len(dog_rows)
    res["ats_disagreement_gt_3pts"] = {
        "n_candidates": len(cand), "n_pushes_excluded": pushes,
        "n_decided": decided, "candidate_cover_rate": (covers / decided) if decided else None,
    }
    res["favorite_underdog_diagnostic"] = {
        "n_candidates": len(cand), "n_pickem_candidates": pickem,
        "n_favorite_backed": len(fav_rows), "n_underdog_backed": len(dog_rows),
        "underdog_share_of_non_pickem": (len(dog_rows) / non_pickem) if non_pickem else None,
        "favorite_share_of_non_pickem": (len(fav_rows) / non_pickem) if non_pickem else None,
        "favorite_backed": subset_stats(fav_rows),
        "underdog_backed": subset_stats(dog_rows),
    }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    prereg = check_inputs(a.games)
    chall = run_engine(load(a.games, *C_STREAM), C_START)
    v1 = run_engine(load(a.games, *V1_STREAM), V1_START)
    coef = fit_calibration(list(chall.values()))
    res = {"label": "SCREEN", "research_only": True,
           "prereg_sha256": prereg, "corpus_sha256": CORPUS_SHA,
           "challenger_constants": {"start": C_START, "regress": C_REGRESS,
                                    "hfa": C_HFA, "k": C_K, "stream_seasons": list(C_STREAM)},
           "calibration_fit_on_2010_2017_only": coef,
           "elo_v1_reference_published": {
               "moneyline_full_set": "delta +0.0274 [+0.0188, +0.0356], n=2219, DOES_NOT_BEAT_CLOSE"},
           "results": evaluate(chall, v1, coef)}
    a.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    r = res["results"]
    print("SCREEN n=", r["n"], "coef=", {k: round(v, 5) for k, v in coef.items() if isinstance(v, float)})
    print("logloss:", {k: round(v, 5) for k, v in r["logloss"].items()})
    for k in ("delta_challenger_minus_market", "delta_challenger_minus_elo_v1",
              "delta_elo_v1_minus_market_descriptive"):
        d = r[k]
        print(k, round(d["mean"], 5), [round(d["ci95_lo"], 5), round(d["ci95_hi"], 5)])
    print("verdicts:", r["verdict_vs_close"], "/", r["verdict_vs_elo_v1"])
    print("ats:", r["ats_disagreement_gt_3pts"])
    fd = r["favorite_underdog_diagnostic"]
    print("fav/dog: n=", fd["n_candidates"], "pickem=", fd["n_pickem_candidates"],
          "fav=", fd["n_favorite_backed"], "dog=", fd["n_underdog_backed"],
          "dog_share=", None if fd["underdog_share_of_non_pickem"] is None else round(fd["underdog_share_of_non_pickem"], 4))


if __name__ == "__main__":
    main()
