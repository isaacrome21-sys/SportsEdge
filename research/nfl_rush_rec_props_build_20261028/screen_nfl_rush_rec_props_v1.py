"""NFL_RUSH_REC_PROPS_V1 construction + design screen (RESEARCH_ONLY).

Implements research/nfl_rush_rec_props_design_20261028/DESIGN_NFL_RUSH_REC_PROPS_V1.md
under the readings committed in BUILD_RECORD.md (this directory) before any
outcome was computed. Prices nothing; freezes nothing; opens no clock.

Usage: python screen_nfl_rush_rec_props_v1.py --data DIR --out results.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
EVAL_PATH = REPO / "research/nfl_props_part2_20261018/eval_nfl_props_calibration_v1.py"
EVAL_SHA = "66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b"
DESIGN_PATH = REPO / "research/nfl_rush_rec_props_design_20261028/DESIGN_NFL_RUSH_REC_PROPS_V1.md"
DESIGN_SHA = "d088676745914f11215352bbafcdbde5cd759d9d1e7d21d2c5ebaccfe222ad8c"
DATA_PINS = {
    "ps_2018.csv.gz": "15730d75271ec10affc412b50b22fc8e3d6ce8f442d377936f65bc0044ef15bf",
    "ps_2019.csv.gz": "d143b91c62380bed1587fe390e594d0e5555e8ebac81fcc7212ad7224115caf2",
    "ps_2020.csv.gz": "e23a81d6ed3c94bd2dd14a5ee3ed94584a69e67fdb985c1ba0de4ccbc5a2bdcc",
    "ps_2021.csv.gz": "a2fb266576a1bde5d7978005a5f6ccf83e3c023234da500d38cf6a14f40a01c8",
    "ps_2022.csv.gz": "2b7dca6814993b9fd6ad3d4fdc56131663311bbe83281126e1ac441620d824ba",
    "ps_2023.csv.gz": "b7590543f3c81dceb17d7577a1dce7b8ff1a9aacf0f562e3d7bbc7e60f37bc9b",
    "ps_2024.csv.gz": "629b77e0c88d361f8b5c4a850e7866013aa670b7a5a94b7f1d0c591adf18f971",
    "sp_2025_played_v2.csv.gz": "f2768ac1c71e5ed616307106df32ef8ad4fc7d548bb96600f6a616fb631f7b48",
}
SCREEN_SEED = 20261028  # BUILD_RECORD F3: set explicitly on the imported evaluator
TRAIN, SCORED = (2018, 2019), tuple(range(2020, 2026))
# design constants (§3)
K_V, K_S, HALF_LIFE = 4.0, 2.0, 3.0
K_E = {"RUSH_YDS": 60.0, "REC_YDS": 50.0}
K_C = 50.0
OPP = {"RUSH_YDS": "carries", "REC_YDS": "targets", "RECEPTIONS": "targets"}
YARDS = {"RUSH_YDS": "rushing_yards", "REC_YDS": "receiving_yards", "RECEPTIONS": "receiving_yards"}
MARKETS = ("RUSH_YDS", "REC_YDS", "RECEPTIONS")
UNPRICEABLE_MAX = 0.005
CAL_MAX_GAP = 0.05
STAB_FRAC = 0.01
FLOOR_MU, FLOOR_VAR, NB_TAIL = 1e-6, 1e-9, 1e-9


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_evaluator():
    if sha(EVAL_PATH) != EVAL_SHA:
        raise SystemExit("incumbent evaluator hash mismatch")
    spec = importlib.util.spec_from_file_location("eval_nfl_props_calibration_v1", EVAL_PATH)
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    ev.SEED = SCREEN_SEED  # F3: explicit override; pinned file not edited
    return ev


def check_data(data: Path) -> dict:
    files = sorted(p.name for p in data.glob("ps_*.csv.gz")) + sorted(p.name for p in data.glob("sp_*.csv.gz"))
    if sorted(files) != sorted(DATA_PINS):
        raise SystemExit(f"loader-visible file set != pinned set: {files}")
    for name, h in DATA_PINS.items():
        if sha(data / name) != h:
            raise SystemExit(f"data hash mismatch {name}")
    return dict(DATA_PINS)


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


COLS = ("attempts", "passing_yards", "carries", "rushing_yards", "targets", "receptions", "receiving_yards")


def load_full(data: Path):
    """Same rows/order as the incumbent load(), plus team. Returns (games, teamV)."""
    games: dict = defaultdict(lambda: defaultdict(list))
    team_v: dict = defaultdict(lambda: defaultdict(lambda: {"carries": 0.0, "targets": 0.0}))
    files = sorted(data.glob("ps_*.csv.gz")) + sorted(data.glob("sp_*.csv.gz"))
    for p in files:
        with gzip.open(p, "rt") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") != "REG":
                    continue
                s, w = int(r["season"]), int(r["week"])
                team = r.get("recent_team") if "recent_team" in r else r.get("team")
                row = {k: f(r.get(k)) for k in COLS}
                games[s][r["player_id"]].append((w, r.get("position") or "", team or "", row))
                tv = team_v[s][(w, team or "")]
                tv["carries"] += row["carries"]
                tv["targets"] += row["targets"]
    for s in games:
        for pid in games[s]:
            games[s][pid].sort(key=lambda t: t[0])
    return games, team_v


def strip_team(games):
    return {s: {pid: [(w, pos, row) for (w, pos, _t, row) in g] for pid, g in ps.items()} for s, ps in games.items()}


class Cum:
    """Per-season sums by week; earlier(s, w) = sum over weeks < w of season s if that set is
    non-empty (vec[3] counts members), else the previous season's full sum (incumbent league_pool rule)."""

    def __init__(self):
        self.by = defaultdict(lambda: defaultdict(lambda: np.zeros(4)))

    def add(self, s, w, vec):
        self.by[s][w] += np.asarray(vec, float)

    def finalize(self):
        self.total = {s: sum(d.values(), np.zeros(4)) for s, d in self.by.items()}

    def earlier(self, s, w):
        acc = sum((v for wk, v in self.by.get(s, {}).items() if wk < w), np.zeros(4))
        if acc[3] > 0:
            return acc
        return self.total.get(s - 1, np.zeros(4))


def realized(market, games, team_v, s, pid, w):
    g = [t for t in games[s][pid] if t[0] == w]
    assert len(g) == 1, (s, pid, w)
    _, _, team, row = g[0]
    V = team_v[s][(w, team)][OPP[market]]
    return team, row, V


def build_pools(market, games, team_v, inc_rows):
    """G's pool membership (F5b): incumbent qualified rows. vec = [share_sum, n_share, yards_or_rec, opps] ...
    Stored as two Cum objects: share (sum share, count) and efficiency (num, den)."""
    share, eff = Cum(), Cum()
    for s, rows in inc_rows.items():
        for (w, pid, _prior, _y) in rows:
            _, row, V = realized(market, games, team_v, s, pid, w)
            opp = row[OPP[market]]
            num = row["receptions"] if market == "RECEPTIONS" else row[YARDS[market]]
            if V > 0:
                share.add(s, w, [opp / V, 1.0, 0, 1.0])
            else:
                share.add(s, w, [0, 0, 0, 1.0])
            eff.add(s, w, [num, opp, 0, 1.0])
    share.finalize(); eff.finalize()
    league = Cum()
    for s, d in team_v.items():
        for (w, _team), v in d.items():
            league.add(s, w, [v[OPP[market]], 1.0, 0, 1.0])
    league.finalize()
    return share, eff, league


def point_in_time(market, games, team_v, pools, s, pid, w):
    """Design §3.1-3.2 under BUILD_RECORD readings. Returns dict of n_hat, e_hat/p_hat, sum_w."""
    share, eff, league = pools
    idx = [i for i, t in enumerate(games[s][pid]) if t[0] == w]
    assert len(idx) == 1
    i = idx[0]
    prior = games[s][pid][:i]
    team = games[s][pid][i][2]
    opp = OPP[market]
    # pools
    sp = share.earlier(s, w)
    S = sp[0] / sp[1] if sp[1] > 0 else float("nan")
    ep = eff.earlier(s, w)
    E = ep[0] / ep[1] if ep[1] > 0 else float("nan")
    lp = league.earlier(s, w)
    L = lp[0] / lp[1] if lp[1] > 0 else float("nan")
    # V-hat: current team's team-games in strictly earlier weeks
    tvs = [v[opp] for (wk, t), v in team_v[s].items() if t == team and wk < w]
    v_hat = (sum(tvs) + K_V * L) / (len(tvs) + K_V)
    # share EWMA over prior played games with current team (R5), per played game (F5a)
    obs = []
    for (wk, _pos, t, row) in prior:
        if t != team:
            continue
        V = team_v[s][(wk, t)][opp]
        if V > 0:
            obs.append(row[opp] / V)
    sw = sws = 0.0
    for j, x in enumerate(reversed(obs)):
        wt = 0.5 ** (j / HALF_LIFE)
        sw += wt
        sws += wt * x
    s_hat = (sws + K_S * S) / (sw + K_S)
    n_hat = max(s_hat * v_hat, FLOOR_MU)
    tot_opp = sum(r[opp] for (_, _, _, r) in prior)
    if market == "RECEPTIONS":
        tot = sum(r["receptions"] for (_, _, _, r) in prior)
        k = K_C
    else:
        tot = sum(r[YARDS[market]] for (_, _, _, r) in prior)
        k = K_E[market]
    rate = (tot + k * E) / (tot_opp + k)
    return {"n_hat": n_hat, "rate": rate, "sum_w": sw, "prior_stat": None}


def fit_constants(market, games, team_v, pools, inc_rows):
    """F1 r_N and sigma^2 on 2018-2019 training rows only (R9)."""
    num = den = 0.0
    sig = []
    seasons_used = set()
    for s in TRAIN:
        for (w, pid, prior, y) in inc_rows.get(s, []):
            ev_pool_ok = pools[1].earlier(s, w)[3] > 0
            if not ev_pool_ok:
                continue
            seasons_used.add(s)
            pit = point_in_time(market, games, team_v, pools, s, pid, w)
            _, row, _ = realized(market, games, team_v, s, pid, w)
            N, nh = row[OPP[market]], pit["n_hat"]
            num += nh * nh
            den += (N - nh) ** 2 - nh
            if market != "RECEPTIONS" and N > 0:
                sig.append((row[YARDS[market]] - N * pit["rate"]) ** 2 / N)
    assert seasons_used <= set(TRAIN)
    r_n = num / den if den > 0 else math.inf
    sigma2 = float(np.mean(sig)) if sig else None
    return r_n, sigma2


def m_cdf(market, n_hat, rate, r_n, sigma2, grid):
    if market == "RECEPTIONS":
        p = min(max(rate, 0.0), 1.0)
        if math.isinf(r_n):
            dist = stats.poisson(n_hat)
        else:
            dist = stats.nbinom(r_n, r_n / (r_n + n_hat))
        nmax = 0
        while dist.sf(nmax) >= NB_TAIL:
            nmax += 1
        ns = np.arange(nmax + 1)
        pn = dist.pmf(ns)
        kk = np.clip(grid, -1, None)
        cdf = np.zeros_like(grid, dtype=float)
        for n, w in zip(ns, pn):
            cdf += w * stats.binom.cdf(kk, n, p)
        return np.where(grid < 0, 0.0, cdf)
    mu = max(n_hat * rate, FLOOR_MU)
    var_n = n_hat if math.isinf(r_n) else n_hat + n_hat * n_hat / r_n
    var = max(n_hat * sigma2 + rate * rate * var_n, FLOOR_VAR)
    shape = mu * mu / var
    return stats.gamma.cdf(grid, shape, scale=var / mu)


def p_over(cdf, line, count, ev, grid):
    if count:
        return 1.0 - float(cdf[int(line - 0.5) - ev.GRID_LO])
    return 1.0 - float(np.interp(line, grid, cdf))


def deciles(rows, key):
    order = sorted(rows, key=lambda r: r[key])
    n = len(order)
    parts = [order[k * n // 10:(k + 1) * n // 10] for k in range(10)]
    return [{"mean_p_over": float(np.mean([r[key] for r in p])),
             "realized_over": float(np.mean([r["over"] for r in p])), "n": len(p)} for p in parts]


def run(data: Path) -> dict:
    ev = load_evaluator()
    hashes = check_data(data)
    games, team_v = load_full(data)
    ev_data = ev.load(data)
    assert strip_team(games) == {s: dict(d) for s, d in ev_data.items()}, "loader mismatch vs incumbent"
    grid = np.arange(ev.GRID_LO, ev.GRID_HI + 1, dtype=float)
    ev_out = ev.evaluate(ev_data)  # incumbent's own output for R12
    out = {"design_sha256": sha(DESIGN_PATH), "build_record_sha256": sha(HERE / "BUILD_RECORD.md"),
           "evaluator_sha256": EVAL_SHA, "data_sha256": hashes, "bootstrap_seed": ev.SEED,
           "markets": {}}
    assert out["design_sha256"] == DESIGN_SHA
    zero_v = sum(1 for s in team_v for v in team_v[s].values() if v["carries"] == 0 or v["targets"] == 0)
    tv_all = [v["carries"] for s in team_v for v in team_v[s].values()]
    tt_all = [v["targets"] for s in team_v for v in team_v[s].values()]
    out["team_volume_report"] = {"team_games": len(tv_all), "zero_carries_or_targets_team_games": zero_v,
                                 "carries_mean": float(np.mean(tv_all)), "targets_mean": float(np.mean(tt_all))}
    for market in MARKETS:
        cfg = ev.MARKETS[market]
        inc_rows = ev.build(ev_data, cfg)
        pools = build_pools(market, games, team_v, inc_rows)
        r_n, sigma2 = fit_constants(market, games, team_v, pools, inc_rows)
        cv = ev_out[market]["cv_train"]
        rows, unpriceable, integrity = [], 0, []
        for s in SCORED:
            for (w, pid, prior, y) in inc_rows.get(s, []):
                if w < 4:
                    continue
                # R6 alignment
                i = [k for k, t in enumerate(games[s][pid]) if t[0] == w][0]
                mine = [t[3][cfg["stat"]] for t in games[s][pid][:i]]
                if mine != list(prior):
                    integrity.append(f"prior misalignment {s} {pid} {w}")
                pool = ev.league_pool(inc_rows, s, w)
                mu_inc = ev.mu_for(prior, pool)
                c_inc = ev.candidate_cdf(mu_inc, cv, cfg["count"], grid)
                c_b1, c_b2 = ev.emp_cdf(prior, grid), ev.emp_cdf(pool, grid)
                pit = point_in_time(market, games, team_v, pools, s, pid, w)
                c_m = m_cdf(market, pit["n_hat"], pit["rate"], r_n, sigma2, grid)
                if not np.all(np.isfinite(c_m)) or not math.isfinite(pit["n_hat"] * pit["rate"]):
                    unpriceable += 1
                    continue
                line = np.floor(np.median(prior)) + 0.5
                rows.append({"block": f"{s}-W{w:02d}", "season": s,
                             "crps_m": ev.crps(c_m, y, grid), "crps_inc": ev.crps(c_inc, y, grid),
                             "crps_b1": ev.crps(c_b1, y, grid), "crps_b2": ev.crps(c_b2, y, grid),
                             "p_m": p_over(c_m, line, cfg["count"], ev, grid),
                             "p_inc": p_over(c_inc, line, cfg["count"], ev, grid),
                             "over": float(y > line), "prior_dominated": pit["sum_w"] < K_S,
                             "pit_m": float(np.interp(y, grid, c_m))})
        n_total = len(rows) + unpriceable
        # R12: INC arm equals incumbent evaluate() output
        inc_mean = {"CANDIDATE": float(np.mean([r["crps_inc"] for r in rows])),
                    "B1": float(np.mean([r["crps_b1"] for r in rows])),
                    "B2": float(np.mean([r["crps_b2"] for r in rows]))}
        if unpriceable == 0:
            if n_total != ev_out[market]["n"]:
                integrity.append("INC n != evaluator n")
            for a in inc_mean:
                if not math.isclose(inc_mean[a], ev_out[market]["crps"][a], rel_tol=1e-12, abs_tol=1e-12):
                    integrity.append(f"INC {a} CRPS != evaluator")
        res = {"n_rows": n_total, "unpriceable": unpriceable, "r_N": r_n if math.isfinite(r_n) else "POISSON",
               "sigma2": sigma2, "incumbent_cv_train": cv, "integrity_failures": integrity}
        if integrity or unpriceable / max(n_total, 1) > UNPRICEABLE_MAX:
            res["verdict"] = "NOT_EXECUTABLE"
            out["markets"][market] = res
            continue
        blocks = [r["block"] for r in rows]
        assert ev.SEED == SCREEN_SEED
        res["crps"] = {"M": float(np.mean([r["crps_m"] for r in rows])), "INC": inc_mean["CANDIDATE"],
                       "B1": inc_mean["B1"], "B2": inc_mean["B2"]}
        res["delta_vs_INC"] = ev.boot([r["crps_m"] - r["crps_inc"] for r in rows], blocks)
        assert ev.SEED == SCREEN_SEED
        res["delta_vs_B1"] = ev.boot([r["crps_m"] - r["crps_b1"] for r in rows], blocks)
        assert ev.SEED == SCREEN_SEED
        res["delta_vs_B2"] = ev.boot([r["crps_m"] - r["crps_b2"] for r in rows], blocks)
        dm, di = deciles(rows, "p_m"), deciles(rows, "p_inc")
        gap = lambda d: abs(d["mean_p_over"] - d["realized_over"])
        res["deciles_M"], res["deciles_INC"] = dm, di
        res["gaps"] = {"M_top": gap(dm[9]), "M_bottom": gap(dm[0]), "INC_top": gap(di[9]), "INC_bottom": gap(di[0])}
        per = {}
        for s in SCORED:
            rs = [r for r in rows if r["season"] == s]
            per[s] = {"n": len(rs), "M": float(np.mean([r["crps_m"] for r in rs])),
                      "INC": float(np.mean([r["crps_inc"] for r in rs]))}
        res["per_season"] = per
        res["pit_hist_M"] = np.histogram([r["pit_m"] for r in rows], bins=10, range=(0, 1))[0].tolist()
        res["share_prior_dominated"] = float(np.mean([r["prior_dominated"] for r in rows]))
        g = res["gaps"]
        legs = {
            "1_beats_INC": res["delta_vs_INC"]["ci95_hi"] < 0,
            "2_beats_B1_B2": res["delta_vs_B1"]["ci95_hi"] < 0 and res["delta_vs_B2"]["ci95_hi"] < 0,
            "3_extreme_deciles": (g["M_top"] <= CAL_MAX_GAP and g["M_bottom"] <= CAL_MAX_GAP
                                  and g["M_top"] <= g["INC_top"] and g["M_bottom"] <= g["INC_bottom"]),
            "4_stability": all(v["M"] - v["INC"] <= STAB_FRAC * v["INC"] for v in per.values()),
        }
        res["legs"] = legs
        res["verdict"] = "SCREEN_PASS" if all(legs.values()) else "SCREEN_FAIL"
        out["markets"][market] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    res = run(a.data)
    a.out.write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({m: v["verdict"] for m, v in res["markets"].items()}))


if __name__ == "__main__":
    main()
