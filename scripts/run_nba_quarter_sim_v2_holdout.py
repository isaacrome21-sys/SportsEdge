#!/usr/bin/env python3
"""Pre-registered V1 vs V2 (regulation-share fix) holdout on 2025-26.

V2 calibration constants come from ALL 2024-25 quarter games and are frozen.
V1 is the unchanged in-season cold calibration. Ratings and naive stand-in
lines are walk-forward on 2025-26 only. Research only; market baseline MISSING.
Usage: --fit-cache 2024-25 dir --holdout-cache 2025-26 dir
"""
import argparse, json, sys, pathlib
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_nba_asof_harness import load
from sportsedge.sports.nba.asof_team_ratings import fit_asof
from sportsedge.sports.nba.asof_harness import _score
from sportsedge.sports.nba.quarter_joint_sim import calibrate, simulate, simulate_v2, markets


def run(fit_cache, hold_cache, n_paths=3000, min_team_games=10):
    _, fit_q, _ = load(fit_cache)
    frozen = calibrate(fit_q, datetime(2100, 1, 1, tzinfo=timezone.utc))
    games, qs, _ = load(hold_cache)
    qmap = {q.game_id: q for q in qs}
    games = sorted((g for g in games if g.game_id in qmap), key=lambda g: (g.start, g.game_id))
    by_day = defaultdict(list)
    for g in games:
        by_day[g.start.date()].append(g)
    rows = {a: {"TOTAL": [], "H1": [], "Q1": [], "ML": []} for a in ("V1", "V2")}
    diag = {"V1": [], "V2": []}; ot_sim = {"V1": [], "V2": []}; ot_act = []
    for day in sorted(by_day):
        slate = by_day[day]
        cutoff = min(g.start for g in slate)
        train = [g for g in games if g.start < cutoff]
        if len(train) < 30:
            continue
        r = fit_asof(train, cutoff)
        cal_v1 = calibrate([qmap[g.game_id] for g in train], cutoff)
        tq = [qmap[g.game_id] for g in train]
        lines = {
            "TOTAL": sum(sum(q.home_lines) + sum(q.away_lines) for q in tq) / len(tq),
            "H1": sum(sum(q.home_lines[:2]) + sum(q.away_lines[:2]) for q in tq) / len(tq),
            "Q1": sum(q.home_lines[0] + q.away_lines[0] for q in tq) / len(tq),
        }
        for g in slate:
            if min(r.games_by_team.get(g.home, 0), r.games_by_team.get(g.away, 0)) < min_team_games:
                continue
            p = r.predict(g.home, g.away)
            seed = int(g.game_id) % (2 ** 31) if g.game_id.isdigit() else 0
            q = qmap[g.game_id]
            y = {"TOTAL": sum(q.home_lines) + sum(q.away_lines),
                 "H1": sum(q.home_lines[:2]) + sum(q.away_lines[:2]),
                 "Q1": q.home_lines[0] + q.away_lines[0]}
            ot_act.append(int(len(q.home_lines) > 4))
            for arm, (cal, fn) in {"V1": (cal_v1, simulate), "V2": (frozen, simulate_v2)}.items():
                H, A = fn(cal, p["home_points"], p["away_points"], n=n_paths, seed=seed)
                m = markets(H, A)
                sims = {"TOTAL": m["total"], "H1": m["h1_total"], "Q1": m["q1_total"]}
                for k in ("TOTAL", "H1", "Q1"):
                    rows[arm][k].append({"model": float((sims[k] > lines[k]).mean()), "naive": 0.5,
                                         "y": int(y[k] > lines[k])})
                rows[arm]["ML"].append({"model": m["home_ml"], "naive": 0.5,
                                        "y": int(sum(q.home_lines) > sum(q.away_lines))})
                diag[arm].append(float(m["total"].mean()) - y["TOTAL"])
                ot_sim[arm].append(m["went_ot"])
    out = {"prereg": "docs/NBA_QUARTER_SIM_REG_SHARE_V2_PREREG_20261013.md",
           "frozen_2024_25_calibration": {"n_games": frozen.n_games, "reg_share": frozen.reg_share,
                                          "shares": frozen.shares, "rho": frozen.rho,
                                          "ot_mean": frozen.ot_mean, "ot_sd": frozen.ot_sd},
           "actual_ot_rate": sum(ot_act) / len(ot_act), "n": len(ot_act)}
    for arm in ("V1", "V2"):
        out[arm] = {k: {kk: v for kk, v in _score(rows[arm][k]).items() if not kk.startswith("naive")}
                    for k in rows[arm]}
        out[arm]["mean_sim_minus_actual_total"] = sum(diag[arm]) / len(diag[arm])
        out[arm]["sim_ot_rate"] = sum(ot_sim[arm]) / len(ot_sim[arm])
    gate = ("TOTAL", "H1", "Q1")
    wins = [k for k in gate if out["V2"][k]["model_brier"] < out["V1"][k]["model_brier"]
            and out["V2"][k]["model_logloss"] < out["V1"][k]["model_logloss"]]
    worst = max(out["V2"][k]["model_brier"] - out["V1"][k]["model_brier"] for k in gate)
    out["v2_wins"] = wins; out["v2_max_brier_regression"] = worst
    out["decision"] = "PASS_RESEARCH" if len(wins) >= 2 and worst <= 0.002 else "FAIL"
    out.update({"market_baseline": "MISSING", "rest_adj": 0.0, "research_only": True})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-cache", required=True); ap.add_argument("--holdout-cache", required=True)
    a = ap.parse_args()
    print(json.dumps(run(a.fit_cache, a.holdout_cache), indent=2))
