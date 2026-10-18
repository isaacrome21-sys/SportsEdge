"""NFL sides Elo v1 evaluator (PREREG_NFL_SIDES_ELO_V1.md). RESEARCH_EVIDENCE only.

Usage: python eval_nfl_sides_elo_v1.py --games games.csv --out results.json
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
START, REGRESS, HFA, K, SD, PTS_PER_ELO = 1505.0, 1 / 3, 48.0, 20.0, 13.5, 25.0
FIRST_SEASON, FIRST_SCORED, LAST_SCORED = 2015, 2018, 2025
SEED, RESAMPLES = 20261017, 2000


def check_inputs(games_path: Path) -> str:
    want = (HERE / "SPEC_HASHES.txt").read_text().split()[0]
    got = hashlib.sha256((HERE / "PREREG_NFL_SIDES_ELO_V1.md").read_bytes()).hexdigest()
    if got != want:
        raise SystemExit(f"prereg hash mismatch {got}")
    c = hashlib.sha256(games_path.read_bytes()).hexdigest()
    if c != CORPUS_SHA:
        raise SystemExit(f"corpus hash mismatch {c}")
    return got


def american_to_prob(a: float) -> float:
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def devig(a: float, b: float) -> float:
    pa, pb = american_to_prob(a), american_to_prob(b)
    return pa / (pa + pb)


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(path: Path) -> list[dict]:
    rows = []
    for r in csv.DictReader(open(path)):
        s = int(r["season"])
        if s < FIRST_SEASON or r["home_score"] == "" or r["away_score"] == "":
            continue
        rows.append(r)
    rows.sort(key=lambda r: (r["gameday"], r["gametime"] or "00:00", r["game_id"]))
    return rows


def run(rows: list[dict]) -> list[dict]:
    elo: dict[str, float] = defaultdict(lambda: START)
    season = None
    out = []
    i = 0
    while i < len(rows):
        # identical kickoff batch: rate from the same pre-kickoff state
        key = (rows[i]["gameday"], rows[i]["gametime"])
        j = i
        while j < len(rows) and (rows[j]["gameday"], rows[j]["gametime"]) == key:
            j += 1
        batch = rows[i:j]
        s = int(batch[0]["season"])
        if season is not None and s != season:
            for t in list(elo):
                elo[t] = elo[t] + REGRESS * (START - elo[t])
        season = s
        updates = []
        for r in batch:
            h, a = r["home_team"], r["away_team"]
            hfa = 0.0 if r["location"] == "Neutral" else HFA
            d = elo[h] + hfa - elo[a]
            p_home = 1.0 / (1.0 + 10 ** (-d / 400.0))
            margin = float(r["home_score"]) - float(r["away_score"])
            spread = num(r["spread_line"])
            out.append({
                "game_id": r["game_id"], "season": s, "week": int(r["week"]),
                "home": h, "away": a, "elo_home": elo[h], "elo_away": elo[a], "hfa": hfa,
                "p_home_win": p_home, "pred_margin": d / PTS_PER_ELO, "margin": margin,
                "spread_line": spread,
                "p_home_cover": (phi((d / PTS_PER_ELO - spread) / SD) if spread is not None else None),
                "ml": (num(r["home_moneyline"]), num(r["away_moneyline"])),
                "sp": (num(r["home_spread_odds"]), num(r["away_spread_odds"])),
            })
            if margin == 0:
                res, mult = 0.5, 1.0
            else:
                res = 1.0 if margin > 0 else 0.0
                winner_diff = d if margin > 0 else -d
                mult = math.log(abs(margin) + 1) * 2.2 / (0.001 * winner_diff + 2.2)
            shift = K * mult * (res - p_home)
            updates.append((h, a, shift))
        for h, a, shift in updates:
            elo[h] += shift
            elo[a] -= shift
        i = j
    return out


def ll(p: float, y: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def boot(vals, blocks):
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
    return {"mean": float(vals.mean()), "ci95_lo": float(lo), "ci95_hi": float(hi),
            "n": int(len(vals)), "n_blocks": len(keys)}


def evaluate(preds: list[dict]) -> dict:
    out = {}
    for mkt in ("moneyline", "spread"):
        rows = []
        for g in preds:
            if not (FIRST_SCORED <= g["season"] <= LAST_SCORED):
                continue
            if mkt == "moneyline":
                h, a = g["ml"]
                if h is None or a is None or g["margin"] == 0:
                    continue
                y = 1.0 if g["margin"] > 0 else 0.0
                pc, pm, pn, price_h, price_a = g["p_home_win"], devig(h, a), 0.57, h, a
            else:
                h, a = g["sp"]
                if h is None or a is None or g["spread_line"] is None:
                    continue
                diff = g["margin"] - g["spread_line"]
                if diff == 0:
                    continue
                y = 1.0 if diff > 0 else 0.0
                pc, pm, pn, price_h, price_a = g["p_home_cover"], devig(h, a), 0.5, h, a
            rows.append({"block": f"{g['season']}-W{g['week']:02d}", "y": y, "pc": pc, "pm": pm,
                         "pn": pn, "price_h": price_h, "price_a": price_a,
                         "home_fav": (g["spread_line"] or 0) > 0})
        blocks = [r["block"] for r in rows]
        d_cm = [ll(r["pc"], r["y"]) - ll(r["pm"], r["y"]) for r in rows]
        res = {"n": len(rows),
               "logloss": {a: float(np.mean([ll(r[k], r["y"]) for r in rows]))
                           for a, k in (("CANDIDATE", "pc"), ("MARKET", "pm"), ("NAIVE", "pn"))},
               "delta_candidate_minus_market": boot(d_cm, blocks)}
        res["verdict"] = ("BEATS_CLOSE" if res["delta_candidate_minus_market"]["ci95_hi"] < 0
                          else "DOES_NOT_BEAT_CLOSE")
        # descriptive: flat-stake ROI at close where |edge| > 3pp
        pnl, bl, dog = [], [], 0
        for r in rows:
            e = r["pc"] - r["pm"]
            if abs(e) <= 0.03:
                continue
            home = e > 0
            price = r["price_h"] if home else r["price_a"]
            win = (r["y"] == 1.0) == home
            pnl.append((price / 100 if price > 0 else 100 / -price) if win else -1.0)
            bl.append(r["block"])
            is_dog = (price > 0) if mkt == "moneyline" else (home != r["home_fav"])
            dog += int(is_dog)
        res["flat_bets_edge_gt_3pp"] = {"roi": boot(pnl, bl) if pnl else None,
                                        "underdog_share": (dog / len(pnl)) if pnl else None}
        dec = []
        order = sorted(rows, key=lambda r: r["pc"])
        for k in range(10):
            part = order[k * len(order) // 10:(k + 1) * len(order) // 10]
            dec.append({"mean_candidate": float(np.mean([r["pc"] for r in part])),
                        "mean_market": float(np.mean([r["pm"] for r in part])),
                        "realized": float(np.mean([r["y"] for r in part])), "n": len(part)})
        res["calibration_deciles"] = dec
        out[mkt] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    prereg = check_inputs(a.games)
    preds = run(load(a.games))
    res = {"label": "RESEARCH_EVIDENCE", "prereg_sha256": prereg, "corpus_sha256": CORPUS_SHA,
           "constants": {"start": START, "regress": REGRESS, "hfa": HFA, "k": K, "sd": SD,
                         "pts_per_elo": PTS_PER_ELO},
           "results": evaluate(preds)}
    a.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    for m, r in res["results"].items():
        d = r["delta_candidate_minus_market"]
        print(m, r["verdict"], r["n"], {k: round(v, 5) for k, v in r["logloss"].items()},
              round(d["mean"], 5), [round(d["ci95_lo"], 5), round(d["ci95_hi"], 5)],
              r["flat_bets_edge_gt_3pp"])


if __name__ == "__main__":
    main()
