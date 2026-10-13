"""REPRODUCIBLE CALIBRATION STUDY -- branch copy.
Run from the repo root with the study data snapshot in
~/workspace/qbstudy-scratch/ (see the module docstring for sources).
Outputs pin the constants in sportsedge/qb_value.py /
sportsedge/mlb_sp_rgs.py (tests pin them; update deliberately).

MLB SP adjustment ablation: which 538-adaptation wins out-of-sample.

Variants (all point-in-time, strictly-earlier dates):
  V1 team_oppnorm : gap vs team rGS, opponent-normalized game scores
  V2 league_raw   : gap vs trailing league-mean gameScore, raw scores
  V3 team_raw     : gap vs team rGS, raw scores
  V4 league_oppnorm: gap vs trailing league mean, opponent-normalized scores
Plus: current ERA-vs-staff formula (PIT, RA/9 for ERA) and no-adjustment.
Fit 2021-2022 (OLS per variant), eval 2023-2024 on the IDENTICAL game set
(games where every variant is computable). Winner ships.
"""
import json
import os
import statistics
from collections import defaultdict, deque

exec(open(os.path.expanduser("~/workspace/qbstudy-scratch/study_sp.py"))
     .read().split("def main")[0])

P_TRAIL, T_TRAIL, R_TRAIL, MIN_STARTS = 20, 30, 20, 5


def main():
    games = load_games()
    by_date = defaultdict(list)
    for g in games:
        by_date[g["date"]].append(g)

    p_raw = defaultdict(deque)
    p_nrm = defaultdict(deque)   # per-start opponent-normalized (insert-time)
    p_runs = defaultdict(deque)
    p_outs = defaultdict(deque)
    t_raw = defaultdict(deque)
    t_nrm = defaultdict(deque)
    t_runs = defaultdict(deque)
    t_outs = defaultdict(deque)
    team_r = defaultdict(deque)
    lg_pool = deque()  # trailing raw game scores, league-wide

    recs = []
    for date in sorted(by_date):
        season = int(date[:4])
        day = by_date[date]
        # evaluate with prior state
        for g in day:
            for side, oside in (("home", "away"), ("away", "home")):
                sp = g[side + "_sp"]
                pid, tid, oid = sp["id"], g[side + "_id"], g[oside + "_id"]
                if not (len(p_raw[pid]) >= MIN_STARTS and len(t_raw[tid]) >= 5
                        and len(team_r[oid]) >= 10 and len(lg_pool) >= 200):
                    continue
                p_rgs = sum(p_raw[pid]) / len(p_raw[pid])
                t_rgs = sum(t_raw[tid]) / len(t_raw[tid])
                p_rgs_n = sum(p_nrm[pid]) / len(p_nrm[pid])
                t_rgs_n = sum(t_nrm[tid]) / len(t_nrm[tid])
                lg_mean = sum(lg_pool) / len(lg_pool)
                opp_hist = team_r[oid]
                opp_avg = sum(opp_hist) / len(opp_hist)
                resid = g[oside + "_score"] - opp_avg
                p_ra9 = 27 * sum(p_runs[pid]) / max(1, sum(p_outs[pid]))
                t_ra9 = 27 * sum(t_runs[tid]) / max(1, sum(t_outs[tid]))
                avg_ip = (sum(p_outs[pid]) / len(p_outs[pid])) / 3.0
                supp = max(-1.5, min(1.5, t_ra9 - p_ra9))
                cur = max(-2.0, min(2.0, -supp * max(4.0, min(7.0, avg_ip)) / 9.0))
                recs.append({
                    "season": season, "resid": resid, "cur": cur,
                    "v1": p_rgs_n - t_rgs_n,
                    "v2": p_rgs - lg_mean,
                    "v3": p_rgs - t_rgs,
                    "v4": p_rgs_n - lg_mean,
                })
        # advance: insert-time per-start opponent normalization (PIT)
        lg_rg_now = {}
        for t, dq in team_r.items():
            if dq:
                lg_rg_now[t] = sum(dq) / len(dq)
        lg_rg = sum(lg_rg_now.values()) / max(1, len(lg_rg_now))
        for g in day:
            for side, oside in (("home", "away"), ("away", "home")):
                sp = g[side + "_sp"]
                gs = game_score(sp["line"])
                o = outs(sp["line"].get("inningsPitched"))
                if gs is None or o is None:
                    continue
                pid, tid, oid = sp["id"], g[side + "_id"], g[oside + "_id"]
                oh = team_r[oid]
                adj = (gs + 3.0 * (sum(oh) / len(oh) - lg_rg)
                       if len(oh) >= 10 and lg_rg_now else gs)
                for dq, v, n in ((p_raw[pid], gs, P_TRAIL),
                                 (p_nrm[pid], adj, P_TRAIL),
                                 (t_raw[tid], gs, T_TRAIL),
                                 (t_nrm[tid], adj, T_TRAIL)):
                    dq.append(v)
                    if len(dq) > n:
                        dq.popleft()
                rv = float(sp["line"].get("runs", 0))
                for dq, v, n in ((p_runs[pid], rv, P_TRAIL), (p_outs[pid], o, P_TRAIL),
                                 (t_runs[tid], rv, T_TRAIL), (t_outs[tid], o, T_TRAIL)):
                    dq.append(v)
                    if len(dq) > n:
                        dq.popleft()
                lg_pool.append(gs)
                if len(lg_pool) > 3000:
                    lg_pool.popleft()
            for side in ("home", "away"):
                dq = team_r[g[side + "_id"]]
                dq.append(g[side + "_score"])
                if len(dq) > R_TRAIL:
                    dq.popleft()

    fit = [r for r in recs if r["season"] in (2021, 2022)]
    ev = [r for r in recs if r["season"] in (2023, 2024)]
    print(f"fit n={len(fit)} eval n={len(ev)} (identical sample)", flush=True)

    def ols(key):
        n = len(fit)
        mx = sum(r[key] for r in fit) / n
        my = sum(r["resid"] for r in fit) / n
        sxx = sum((r[key] - mx) ** 2 for r in fit)
        sxy = sum((r[key] - mx) * (r["resid"] - my) for r in fit)
        s = sxy / sxx if sxx > 1e-9 else 0.0
        return s, my - s * mx

    coefs = {k: ols(k) for k in ("v1", "v2", "v3", "v4")}
    for k, (s, i) in coefs.items():
        print(f"  {k}: gamma={s:.5f} intercept={i:.3f}", flush=True)
    mse0 = sum(r["resid"] ** 2 for r in ev) / len(ev)
    msec = sum((r["resid"] - r["cur"]) ** 2 for r in ev) / len(ev)
    print(f"  no_adjustment MSE={mse0:.4f}", flush=True)
    print(f"  current_era_formula MSE={msec:.4f}", flush=True)
    out = {}
    for k, (s, i) in coefs.items():
        m = sum((r["resid"] - (i + s * r[k])) ** 2 for r in ev) / len(ev)
        out[k] = {"gamma": s, "intercept": i, "eval_mse": m}
        print(f"  {k} MSE={m:.4f}", flush=True)
    json.dump(out, open(os.path.join(SCRATCH, "sp_ablation.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
