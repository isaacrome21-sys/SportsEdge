#!/usr/bin/env python3
"""Lane 1 (#2384) NFL sides chronological out-of-sample backtest.

Data: nflverse games.csv (free, public; saved locally -- no paid collector is
run). Pass ``--games PATH``. Its sha256 is recorded in the receipt.
Train (fit): REG seasons 2006-2020. Holdout (scored once, never fit):
REG seasons 2021-2025 with both closing moneylines present.

Features are point-in-time: each team's last <=5 completed games of the SAME
season strictly before the game (mirrors PublicContext.schedule).

    python scripts/backtest_nfl_sides_lane1.py --games /path/games.csv --fit
    python scripts/backtest_nfl_sides_lane1.py --games /path/games.csv \
        --out artifacts/nfl_sides_lane1_backtest.json

Research only. No wagering, no stakes; nothing here validates a market.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sportsedge.sports.nfl import side_margin_model as smm  # noqa: E402

HFA = 1.5  # production PRIORS["NFL"] home-field advantage (unchanged)
OLD_SD = 13.7
TRAIN = range(2006, 2021)
HOLDOUT = range(2021, 2026)
BLEND_W = 0.15  # production Lane B ANCHOR_WEIGHT (display blend)
SEED = 20261024
BOOT = 2000


def load(path):
    rows = [r for r in csv.DictReader(open(path, newline=""))
            if r["game_type"] == "REG" and r["result"] not in ("", None)]
    rows.sort(key=lambda r: (r["gameday"], r["gametime"] or "", r["game_id"]))
    hist = defaultdict(list)
    out = []
    for r in rows:
        s, h, a = int(r["season"]), r["home_team"], r["away_team"]
        out.append({"row": r, "season": s, "hm": hist[(s, h)][-5:],
                    "am": hist[(s, a)][-5:], "margin": int(r["result"])})
        hist[(s, h)].append(int(r["result"]))
        hist[(s, a)].append(-int(r["result"]))
    return out


def cdf(x, m, sd):
    return (1 + math.erf((x - m) / (sd * math.sqrt(2)))) / 2


def fit(games):
    train = [g for g in games if g["season"] in TRAIN]
    best = None
    for b10 in range(2, 21):
        for k in (0, 1, 2, 3, 4, 5, 6, 8, 10):
            smm.RATING_B, smm.RATING_K = b10 / 10, float(k)
            sse = sum((g["margin"] - HFA - smm.margin_rating_diff(g["hm"], g["am"])) ** 2
                      for g in train)
            if best is None or sse < best[0]:
                best = (sse, b10 / 10, float(k))
    _, b, k = best
    smm.RATING_B, smm.RATING_K = b, k
    mus = [HFA + smm.margin_rating_diff(g["hm"], g["am"]) for g in train]
    sd = math.sqrt(sum((g["margin"] - mu) ** 2 for g, mu in zip(train, mus)) / len(train))
    emp = defaultdict(float)
    nrm = defaultdict(float)
    for g, mu in zip(train, mus):
        emp[abs(g["margin"])] += 1
        for j in range(0, smm.MAX_ABS_MARGIN + 1):
            p = cdf(j + .5, mu, sd) - cdf(j - .5, mu, sd)
            if j:
                p += cdf(-j + .5, mu, sd) - cdf(-j - .5, mu, sd)
            nrm[j] += p
    # Fit weights where the normal model expects >= 30 training games at
    # |margin| = j (this includes j = 0, so NFL ties get their real ~0.3%
    # rate instead of the normal's ~2.8%); beyond that keep 1.0.
    weights = {j: round(emp[j] / nrm[j], 4) for j in range(0, 36)
               if nrm[j] >= 30}
    return {"RATING_B": b, "RATING_K": k, "MARGIN_SD": round(sd, 2),
            "KEY_WEIGHTS": weights, "n_train": len(train)}


def novig(a, b):
    def imp(x):
        x = float(x)
        return 100 / (x + 100) if x > 0 else -x / (-x + 100)
    pa, pb = imp(a), imp(b)
    return pa / (pa + pb)


def old_mu(g):
    def r(ms):
        return max(-3, min(3, sum(ms) / len(ms) * 0.12)) if ms else 0.0
    return HFA + r(g["hm"]) - r(g["am"])


def old_price(market, side, line, mu):
    m = mu if side == "HOME" else -mu
    dec = 0 if market == "ML" else -line
    whole = market != "ML" and float(line).is_integer()
    push = cdf(dec + .5, m, OLD_SD) - cdf(dec - .5, m, OLD_SD) if whole else 0.0
    win = 1 - cdf(dec + (.5 if whole else 0), m, OLD_SD)
    return win, push, max(0.0, 1 - win - push)


def brier(p, y):
    return (p - y) ** 2


def ll(p, y):
    p = min(1 - 1e-9, max(1e-9, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def boot_ci(diffs):
    rng = random.Random(SEED)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    return [round(means[int(.025 * BOOT)], 6), round(means[int(.975 * BOOT) - 1], 6)]


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def calib(ps, ys):
    pairs = sorted(zip(ps, ys))
    n = len(pairs)
    out = []
    for i in range(10):
        chunk = pairs[i * n // 10:(i + 1) * n // 10]
        mp = sum(p for p, _ in chunk) / len(chunk)
        oy = sum(y for _, y in chunk) / len(chunk)
        out.append({"decile": i + 1, "n": len(chunk), "mean_p": round(mp, 4),
                    "observed": round(oy, 4), "gap_pp": round(100 * (mp - oy), 2)})
    return out


def score(name, ps, ys, base):
    b = [brier(p, y) for p, y in zip(ps, ys)]
    l = [ll(p, y) for p, y in zip(ps, ys)]
    bb = [brier(p, y) for p, y in zip(base, ys)]
    lb = [ll(p, y) for p, y in zip(base, ys)]
    db = [x - y for x, y in zip(b, bb)]
    dl = [x - y for x, y in zip(l, lb)]
    cal = calib(ps, ys)
    return {"model": name, "n": len(ys), "brier": round(sum(b) / len(b), 6),
            "log_loss": round(sum(l) / len(l), 6),
            "brier_minus_market": round(sum(db) / len(db), 6),
            "brier_minus_market_ci95": boot_ci(db),
            "log_loss_minus_market": round(sum(dl) / len(dl), 6),
            "log_loss_minus_market_ci95": boot_ci(dl),
            "max_abs_decile_gap_pp": max(abs(c["gap_pp"]) for c in cal),
            "calibration_deciles": cal}


def evaluate(games):
    hold = [g for g in games if g["season"] in HOLDOUT
            and g["row"]["home_moneyline"] and g["row"]["away_moneyline"]]
    ml = [g for g in hold if g["margin"] != 0]
    ys = [1 if g["margin"] > 0 else 0 for g in ml]
    mkt = [novig(g["row"]["home_moneyline"], g["row"]["away_moneyline"]) for g in ml]
    new, old = [], []
    for g in ml:
        mu = HFA + smm.margin_rating_diff(g["hm"], g["am"])
        w, p, _ = smm.price_side("ML", "HOME", None, mu)
        new.append(w / (1 - p))  # conditional on a decision (ties excluded)
        old.append(old_price("ML", "HOME", None, old_mu(g))[0])
    blend_new = [m + BLEND_W * (x - m) for m, x in zip(mkt, new)]
    blend_old = [m + BLEND_W * (x - m) for m, x in zip(mkt, old)]
    ml_res = [score("market_no_vig_close", mkt, ys, mkt),
              score("lane_a_new_" + smm.MODEL_ID, new, ys, mkt),
              score("lane_a_old_free_models_0.12_cap3", old, ys, mkt),
              score("blend15_new", blend_new, ys, mkt),
              score("blend15_old", blend_old, ys, mkt)]
    # Compression symptom: how many games does each model price as a +EV dog?
    def dog_share(ps):
        dogs = pos = 0
        for g, p, m in zip(ml, ps, mkt):
            for side_p, side_m, price in ((p, m, g["row"]["home_moneyline"]),
                                          (1 - p, 1 - m, g["row"]["away_moneyline"])):
                x = float(price)
                dec = 1 + (x / 100 if x > 0 else 100 / -x)
                if side_p * dec - 1 > 0.02:
                    pos += 1
                    dogs += side_m < 0.5
        return {"positive_ev_sides": pos, "underdog_share": round(dogs / pos, 4) if pos else None}
    spread_std = [abs(x - .5) for x in new]
    symptom = {"new": dog_share(new), "old": dog_share(old),
               "mean_abs_p_minus_half_new": round(sum(spread_std) / len(new), 4),
               "mean_abs_p_minus_half_old": round(sum(abs(x - .5) for x in old) / len(old), 4),
               "mean_abs_p_minus_half_market": round(sum(abs(x - .5) for x in mkt) / len(mkt), 4)}
    # Spreads (nflverse spread_line > 0 means home favored by that many).
    sp = [g for g in hold if g["row"]["spread_line"] and g["row"]["home_spread_odds"]
          and g["row"]["away_spread_odds"]]
    dec_rows, ys_s, new_s, mkt_s, old_s = [], [], [], [], []
    picks_k = picks_n = 0
    gap_k = gap_n = 0
    push_obs = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for g in sp:
        line = -float(g["row"]["spread_line"])  # home handicap
        mu = HFA + smm.margin_rating_diff(g["hm"], g["am"])
        w, p, l = smm.price_side("SPREAD", "HOME", line, mu)
        ow, op, ol = old_price("SPREAD", "HOME", line, old_mu(g))
        x = g["margin"] + line
        if float(line).is_integer() and abs(line) in (3.0, 7.0):
            k = int(abs(line))
            push_obs[k][0] += 1
            push_obs[k][1] += abs(x) < 1e-9
            push_obs[k][2] += p
            push_obs[k][3] += op
        if abs(x) < 1e-9:
            continue
        y = 1 if x > 0 else 0
        cw = w / (w + l)
        ys_s.append(y)
        new_s.append(cw)
        old_s.append(ow / (ow + ol))
        mkt_s.append(novig(g["row"]["home_spread_odds"], g["row"]["away_spread_odds"]))
        pick_home = cw > 0.5
        hit = (y == 1) == pick_home
        picks_n += 1
        picks_k += hit
        if abs(mu + line) >= 2.5:  # model margin vs line gap >= 2.5 pts
            gap_n += 1
            gap_k += hit
    sp_res = [score("market_no_vig_close", mkt_s, ys_s, mkt_s),
              score("lane_a_new_" + smm.MODEL_ID, new_s, ys_s, mkt_s),
              score("lane_a_old_free_models_0.12_cap3", old_s, ys_s, mkt_s),
              score("blend15_new", [m + BLEND_W * (x - m) for m, x in zip(mkt_s, new_s)], ys_s, mkt_s)]
    pushes = {str(k): {"n_games_at_line": v[0], "observed_push_rate": round(v[1] / v[0], 4),
                       "predicted_new": round(v[2] / v[0], 4), "predicted_old": round(v[3] / v[0], 4),
                       "observed_ci95": wilson(v[1], v[0])}
              for k, v in sorted(push_obs.items())}
    def vs_old(a, b, ys_):
        db = [brier(x, y) - brier(z, y) for x, z, y in zip(a, b, ys_)]
        dl = [ll(x, y) - ll(z, y) for x, z, y in zip(a, b, ys_)]
        return {"brier_new_minus_old": round(sum(db) / len(db), 6), "brier_ci95": boot_ci(db),
                "log_loss_new_minus_old": round(sum(dl) / len(dl), 6), "log_loss_ci95": boot_ci(dl)}
    new_vs_old = {"moneyline": vs_old(new, old, ys), "spread": vs_old(new_s, old_s, ys_s)}
    return {"moneyline_home_win": ml_res, "lane_a_new_vs_old": new_vs_old, "compression_symptom": symptom,
            "spread_home_cover_decided": sp_res,
            "ats_hit_rate_all": {"n": picks_n, "hits": picks_k,
                                 "rate": round(picks_k / picks_n, 4), "wilson95": wilson(picks_k, picks_n)},
            "ats_hit_rate_gap_ge_2_5": {"n": gap_n, "hits": gap_k,
                                        "rate": round(gap_k / gap_n, 4) if gap_n else None,
                                        "wilson95": wilson(gap_k, gap_n)},
            "integer_key_push": pushes,
            "n_holdout_games": len(hold), "n_ml_decided": len(ml), "n_ml_ties_excluded": len(hold) - len(ml)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True)
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    sha = hashlib.sha256(Path(a.games).read_bytes()).hexdigest()
    games = load(a.games)
    if a.fit:
        print(json.dumps(fit(games), indent=1))
        return
    # Frozen-parameter check: the module constants must equal a train-only refit.
    frozen = {"RATING_B": smm.RATING_B, "RATING_K": smm.RATING_K,
              "MARGIN_SD": smm.MARGIN_SD, "KEY_WEIGHTS": dict(smm.KEY_WEIGHTS)}
    refit = fit(games)
    smm.RATING_B, smm.RATING_K = frozen["RATING_B"], frozen["RATING_K"]
    match = all(refit[k] == frozen[k] for k in ("RATING_B", "RATING_K", "MARGIN_SD")) and \
        {int(k): v for k, v in refit["KEY_WEIGHTS"].items()} == frozen["KEY_WEIGHTS"]
    res = evaluate(games)
    ml_new = res["moneyline_home_win"][1]
    ml_blend = res["moneyline_home_win"][3]
    passes = {
        "lane_a_new_ml_brier_and_logloss_at_or_below_market":
            ml_new["brier_minus_market"] <= 0 and ml_new["log_loss_minus_market"] <= 0,
        "blend15_new_ml_brier_and_logloss_at_or_below_market":
            ml_blend["brier_minus_market"] <= 0 and ml_blend["log_loss_minus_market"] <= 0,
        "lane_a_new_ml_calibration_within_3pp_every_decile": ml_new["max_abs_decile_gap_pp"] <= 3,
        "blend15_new_ml_calibration_within_3pp_every_decile": ml_blend["max_abs_decile_gap_pp"] <= 3,
    }
    receipt = {"schema": "SPORTSEDGE_NFL_SIDES_LANE1_BACKTEST_V1", "model_id": smm.MODEL_ID,
               "research_only": True, "validated_profitability": False,
               "data": {"source": "nflverse games.csv (public, free; saved copy)", "sha256": sha},
               "train_seasons": [TRAIN.start, TRAIN.stop - 1],
               "holdout_seasons": [HOLDOUT.start, HOLDOUT.stop - 1],
               "frozen_params": {**frozen, "KEY_WEIGHTS": {str(k): v for k, v in frozen["KEY_WEIGHTS"].items()}},
               "frozen_params_equal_train_only_refit": match,
               "bootstrap": {"resamples": BOOT, "seed": SEED},
               "work_order_pass_checks": passes, "results": res}
    text = json.dumps(receipt, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
