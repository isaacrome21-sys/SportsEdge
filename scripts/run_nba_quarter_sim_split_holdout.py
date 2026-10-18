#!/usr/bin/env python3
"""Pre-registered split test: (a) frozen calibration alone, (b) OT-frequency
margin-dispersion fix with c calibrated ONLY on a 2024-25 walk-forward.
Prereg: docs/NBA_QUARTER_SIM_FROZEN_CAL_AND_OT_FIX_PREREG_20261013.md
Usage: PYTHONPATH=. python scripts/run_nba_quarter_sim_split_holdout.py --fit-cache D --holdout-cache D
Research only; market baseline MISSING; rest_adj 0.
"""
import argparse, json, sys, pathlib
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_nba_asof_harness import load
from sportsedge.sports.nba.asof_team_ratings import fit_asof
from sportsedge.sports.nba.asof_harness import _score
from sportsedge.sports.nba.quarter_joint_sim import (OT_FIX_GRID, calibrate, markets, simulate,
                                                    simulate_margin_scaled)


def walk(cache, arms, n_paths=3000, min_team_games=10):
    """Yield per-game dicts {arm: markets} with actuals, V1-style walk-forward."""
    games, qs, _ = load(cache)
    qmap = {q.game_id: q for q in qs}
    games = sorted((g for g in games if g.game_id in qmap), key=lambda g: (g.start, g.game_id))
    by_day = defaultdict(list)
    for g in games:
        by_day[g.start.date()].append(g)
    for day in sorted(by_day):
        slate = by_day[day]
        cutoff = min(g.start for g in slate)
        train = [g for g in games if g.start < cutoff]
        if len(train) < 30:
            continue
        r = fit_asof(train, cutoff)
        tq = [qmap[g.game_id] for g in train]
        cal = calibrate(tq, cutoff)
        lines = {"TOTAL": sum(sum(q.home_lines) + sum(q.away_lines) for q in tq) / len(tq),
                 "H1": sum(sum(q.home_lines[:2]) + sum(q.away_lines[:2]) for q in tq) / len(tq),
                 "Q1": sum(q.home_lines[0] + q.away_lines[0] for q in tq) / len(tq)}
        for g in slate:
            if min(r.games_by_team.get(g.home, 0), r.games_by_team.get(g.away, 0)) < min_team_games:
                continue
            p = r.predict(g.home, g.away)
            seed = int(g.game_id) % (2 ** 31) if g.game_id.isdigit() else 0
            q = qmap[g.game_id]
            out = {"lines": lines, "q": q, "arms": {}}
            for name, fn in arms.items():
                out["arms"][name] = markets(*fn(cal, p["home_points"], p["away_points"], n_paths, seed))
            yield out


def reg_tie_rate(m):
    return float((m["went_ot"]))


def calibrate_c(fit_cache):
    arms = {f"c{c}": (lambda cal, h, a, n, s, c=c: simulate_margin_scaled(cal, h, a, c=c, n=n, seed=s))
            for c in OT_FIX_GRID}
    sims = defaultdict(list); act = []
    for row in walk(fit_cache, arms):
        act.append(int(len(row["q"].home_lines) > 4))
        for k, m in row["arms"].items():
            sims[k].append(m["went_ot"])
    actual = sum(act) / len(act)
    table = {c: sum(sims[f"c{c}"]) / len(sims[f"c{c}"]) for c in OT_FIX_GRID}
    best = min(OT_FIX_GRID, key=lambda c: (abs(table[c] - actual), -c))
    return best, actual, table, len(act)


def main(fit_cache, hold_cache):
    _, fit_q, _ = load(fit_cache)
    frozen = calibrate(fit_q, datetime(2100, 1, 1, tzinfo=timezone.utc))
    c, act24, table, n24 = calibrate_c(fit_cache)
    arms = {
        "V1": lambda cal, h, a, n, s: simulate(cal, h, a, n=n, seed=s),
        "FROZEN_CAL": lambda cal, h, a, n, s: simulate(frozen, h, a, n=n, seed=s),
        "OT_FIX": lambda cal, h, a, n, s: simulate_margin_scaled(cal, h, a, c=c, n=n, seed=s),
    }
    rows = {k: defaultdict(list) for k in arms}; diag = {k: [] for k in arms}; ot = {k: [] for k in arms}; act = []
    for row in walk(hold_cache, arms):
        q, L = row["q"], row["lines"]
        y = {"TOTAL": sum(q.home_lines) + sum(q.away_lines), "H1": sum(q.home_lines[:2]) + sum(q.away_lines[:2]),
             "Q1": q.home_lines[0] + q.away_lines[0]}
        act.append(int(len(q.home_lines) > 4))
        for k, m in row["arms"].items():
            sims = {"TOTAL": m["total"], "H1": m["h1_total"], "Q1": m["q1_total"]}
            for mk in sims:
                rows[k][mk].append({"model": float((sims[mk] > L[mk]).mean()), "naive": 0.5, "y": int(y[mk] > L[mk])})
            rows[k]["ML"].append({"model": m["home_ml"], "naive": 0.5,
                                  "y": int(sum(q.home_lines) > sum(q.away_lines))})
            diag[k].append(float(m["total"].mean()) - y["TOTAL"]); ot[k].append(m["went_ot"])
    out = {"prereg": "docs/NBA_QUARTER_SIM_FROZEN_CAL_AND_OT_FIX_PREREG_20261013.md",
           "c_fit_2024_25": {"c": c, "actual_ot_rate": act24, "n": n24, "grid_sim_ot_rate": table},
           "holdout_n": len(act), "holdout_actual_ot_rate": sum(act) / len(act)}
    for k in arms:
        out[k] = {mk: {kk: v for kk, v in _score(rows[k][mk]).items() if not kk.startswith("naive")} for mk in rows[k]}
        out[k]["mean_sim_minus_actual_total"] = sum(diag[k]) / len(diag[k])
        out[k]["sim_ot_rate"] = sum(ot[k]) / len(ot[k])
    g = ("TOTAL", "H1", "Q1")
    reg = lambda k: max(out[k][m]["model_brier"] - out["V1"][m]["model_brier"] for m in g)
    wins = [m for m in g if out["FROZEN_CAL"][m]["model_brier"] < out["V1"][m]["model_brier"]
            and out["FROZEN_CAL"][m]["model_logloss"] < out["V1"][m]["model_logloss"]]
    out["a_decision"] = {"wins": wins, "max_brier_regression": reg("FROZEN_CAL"),
                         "decision": "PASS_RESEARCH" if len(wins) >= 2 and reg("FROZEN_CAL") <= 0.002 else "FAIL"}
    ot_gap = abs(out["OT_FIX"]["sim_ot_rate"] - out["holdout_actual_ot_rate"])
    ml_ok = out["OT_FIX"]["ML"]["model_brier"] <= out["V1"]["ML"]["model_brier"] + 0.001
    out["b_decision"] = {"ot_gap_pp": 100 * ot_gap, "ml_ok": ml_ok, "max_brier_regression": reg("OT_FIX"),
                         "decision": "PASS_RESEARCH" if ot_gap <= 0.010 and ml_ok and reg("OT_FIX") <= 0.002 else "FAIL"}
    out.update({"market_baseline": "MISSING", "rest_adj": 0.0, "research_only": True})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-cache", required=True); ap.add_argument("--holdout-cache", required=True)
    a = ap.parse_args()
    print(json.dumps(main(a.fit_cache, a.holdout_cache), indent=2))
