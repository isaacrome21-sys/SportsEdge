#!/usr/bin/env python3
"""t272: before/after evaluation of the CFB margin/total model (RESEARCH ONLY).

Inputs (no credit-consuming collector is run):
  * the frozen, sha256-pinned free CFB line archive registered in
    config/research/cfb_historical_market_source_v1.json
    (sportsdataverse/cfbfastR-data cfb_line_odds.csv.gz, pinned commit);
  * ESPN public scoreboard results (keyless) for the same seasons.
Closing reference = median across books of each game's stored line. Market
prices are used ONLY to score; the model inputs are point-in-time results
(last <=5 completed same-season games before kickoff, >=3 required).
Fit season 2024 (results only, never prices); evaluation season 2025.
Output is SCREEN / NOT_VALIDATED; nothing here validates a family.
"""
import argparse, json, math, os, sys

# Runnable from anywhere without PYTHONPATH: put the repo root on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artifacts.free_models import CONTEXT_KEYS, PRIORS, model_probability, score_means

OLD = {"base": 28.0, "sd_total": 18.5, "sd_margin": 19.0, "hfa": 2.5}


def old_means(r):
    rh = max(-3, min(3, 0.12 * r["h_mm"])); ra = max(-3, min(3, 0.12 * r["a_mm"]))
    return OLD["base"] + OLD["hfa"] / 2 + rh, OLD["base"] - OLD["hfa"] / 2 + ra


def _phi(x, m, s):
    return 0.5 * (1 + math.erf((x - m) / (s * math.sqrt(2))))


def old_probs(r):
    hm, am = old_means(r)
    M, T = hm - am, hm + am
    s = r["spread_home"]
    p_cover = 1 - _phi(-s, M, OLD["sd_margin"])
    p_over = 1 - _phi(r["total"], T, OLD["sd_total"])
    return M, T, p_cover, p_over, 1 - _phi(0, M, OLD["sd_margin"])


def new_probs(r):
    from artifacts.free_models import CFB_MARGIN_MODEL as C
    cap = C["rating_cap"]
    ctx = {k: 0.0 for k in CONTEXT_KEYS["CFB"]}
    ctx.update(home_rating=max(-cap, min(cap, C["k_margin"] * r["h_mm"])),
               away_rating=max(-cap, min(cap, C["k_margin"] * r["a_mm"])),
               home_total_rating=r["h_mt"], away_total_rating=r["a_mt"])
    hm, am = score_means("CFB", ctx)
    s = r["spread_home"]
    pc, pp = model_probability("CFB", "SPREAD", "HOME", s, hm, am)
    po, op = model_probability("CFB", "TOTAL", "OVER", r["total"], hm, am)
    pml, _ = model_probability("CFB", "ML", "HOME", None, hm, am)
    pc = pc / (1 - pp) if pp < 1 else 0.5; po = po / (1 - op) if op < 1 else 0.5
    return hm - am, hm + am, pc, po, pml


def metrics(rows, fn, edge=0.03):
    out = {"n": 0, "brier_cover": 0, "brier_over": 0, "brier_ml": 0, "n_ml": 0,
           "dog_side_share": 0, "over_share": 0, "flagged_spread": 0, "flagged_dog": 0,
           "flagged_total": 0, "flagged_over": 0, "flag_spread_hit": 0, "flag_total_hit": 0,
           "margin_vs_close_slope": None, "calib_cover": {}, "calib_ml": {}}
    xs, ys = [], []
    for r in rows:
        cover = r["margin"] + r["spread_home"]; over = r["points"] - r["total"]
        if cover == 0 or over == 0:
            continue
        M, T, pc, po, pml = fn(r)
        out["n"] += 1
        hc, ho, hw = cover > 0, over > 0, r["margin"] > 0
        out["brier_cover"] += (pc - hc) ** 2; out["brier_over"] += (po - ho) ** 2
        home_dog = r["spread_home"] > 0
        pick_home = pc > 0.5
        out["dog_side_share"] += (pick_home == home_dog)
        out["over_share"] += po > 0.5
        if abs(pc - 0.5) >= edge and r["spread_home"] != 0:
            out["flagged_spread"] += 1; out["flagged_dog"] += (pick_home == home_dog)
            out["flag_spread_hit"] += (pick_home == hc)
        if abs(po - 0.5) >= edge:
            out["flagged_total"] += 1; out["flagged_over"] += po > 0.5
            out["flag_total_hit"] += ((po > 0.5) == ho)
        b = min(9, int(pc * 10)); c = out["calib_cover"].setdefault(b, [0, 0, 0.0])
        c[0] += 1; c[1] += hc; c[2] += pc
        if r.get("ml_home_nv") is not None:
            out["n_ml"] += 1; out["brier_ml"] += (pml - hw) ** 2
            b = min(9, int(pml * 10)); c = out["calib_ml"].setdefault(b, [0, 0, 0.0, 0.0])
            c[0] += 1; c[1] += hw; c[2] += pml; c[3] += r["ml_home_nv"]
        xs.append(-r["spread_home"]); ys.append(M)
    n = out["n"]
    for k in ("brier_cover", "brier_over", "dog_side_share", "over_share"):
        out[k] = round(out[k] / n, 4)
    out["brier_ml"] = round(out["brier_ml"] / max(1, out["n_ml"]), 4)
    mx, my = sum(xs) / n, sum(ys) / n
    out["margin_vs_close_slope"] = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                                         / sum((x - mx) ** 2 for x in xs), 3)
    out["mean_abs_margin_gap_to_close"] = round(sum(abs(x - y) for x, y in zip(xs, ys)) / n, 2)
    for key in ("calib_cover", "calib_ml"):
        out[key] = {f"{b/10:.1f}-{(b+1)/10:.1f}": {"n": v[0], "pred": round(v[2] / v[0], 3),
                    "actual": round(v[1] / v[0], 3),
                    **({"market_nv": round(v[3] / v[0], 3)} if len(v) == 4 else {})}
                    for b, v in sorted(out[key].items())}
    out["flag_dog_share"] = round(out["flagged_dog"] / max(1, out["flagged_spread"]), 4)
    out["flag_over_share"] = round(out["flagged_over"] / max(1, out["flagged_total"]), 4)
    out["flag_spread_hit_rate"] = round(out["flag_spread_hit"] / max(1, out["flagged_spread"]), 4)
    out["flag_total_hit_rate"] = round(out["flag_total_hit"] / max(1, out["flagged_total"]), 4)
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--rows", required=True, help="eval rows JSON built from the pinned archive")
    p.add_argument("--season", type=int, default=2025)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    rows = [r for r in json.load(open(a.rows)) if r["season"] == a.season]
    rep = {"season": a.season, "status_label": "SCREEN", "validation": "NOT_VALIDATED",
           "before": metrics(rows, old_probs), "after": metrics(rows, new_probs)}
    json.dump(rep, open(a.out, "w"), indent=1)
    for k in ("n", "brier_cover", "brier_over", "brier_ml", "dog_side_share", "over_share",
              "flagged_spread", "flag_dog_share", "flag_spread_hit_rate", "flagged_total",
              "flag_over_share", "flag_total_hit_rate", "margin_vs_close_slope",
              "mean_abs_margin_gap_to_close"):
        print(f"{k:30} before={rep['before'][k]!s:>8} after={rep['after'][k]!s:>8}")


if __name__ == "__main__":
    main()
