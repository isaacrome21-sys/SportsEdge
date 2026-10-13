"""REPRODUCIBLE CALIBRATION STUDY -- branch copy.
Run from the repo root with the study data snapshot in
~/workspace/qbstudy-scratch/ (see the module docstring for sources).
Outputs pin the constants in sportsedge/qb_value.py /
sportsedge/mlb_sp_rgs.py (tests pin them; update deliberately).

NFL QB-adjustment calibration study (538-adapted, free data only).

See module docstring of the earlier draft for methodology provenance.
This is the full implementation:

  1. Per-QB-game 538 VALUE from nflverse weekly box scores (2015-2024).
  2. Defense adjustment: rolling team QB-VALUE-allowed (20-game trailing),
     minus trailing league-average allowed (538's documented approach).
  3. Rolling QB rating: 0.9*old + 0.1*mean(block) every 10 games; init 0.0
     (replacement level, per 538's "vs undrafted rookie replacement").
  4. Clean backup-start games: announced starter != modal starter of trailing
     10 team games, and the modal starter did not play (att<5 in the game).
  5. Fit (2015-2020): OLS residual ~ gap; mean residual (constant).
     Eval (2021-2024): MSE of {0, declared -3.0, constant, per-QB}.

Point-in-time: everything for game g uses games completed strictly before g.
"""
import csv
import json
import math
import os
import statistics
from collections import defaultdict, deque

SCRATCH = os.path.expanduser("~/workspace/qbstudy-scratch/nflverse")
COEF = {
    "attempts": -2.2, "completions": 3.7, "passing_yards": 1 / 5,
    "passing_tds": 11.3, "interceptions": -14.1, "sacks": -8.0,
    "carries": -1.1, "rushing_yards": 0.6, "rushing_tds": 15.9,
}
FIT = set(range(2015, 2021))
EVAL = set(range(2021, 2025))
TRAIL_TEAM = 10
TRAIL_DEF = 20
BLOCK = 10
MIN_TRAIL_PTS = 5


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def load_qb_games():
    games = []
    for season in sorted(FIT | EVAL):
        path = os.path.join(SCRATCH, f"player_stats_{season}.csv")
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") != "REG":
                    continue
                if (r.get("position") or "").strip() != "QB":
                    continue
                att = fnum(r.get("attempts"))
                if att <= 0:
                    continue
                val = sum(COEF[k] * fnum(r.get(k)) for k in COEF)
                games.append({
                    "season": season, "week": int(r["week"]),
                    "pid": r["player_id"], "pname": r["player_name"],
                    "team": r["recent_team"], "opp": r["opponent_team"],
                    "att": att, "value_raw": val,
                })
    games.sort(key=lambda g: (g["season"], g["week"]))
    return games


def load_schedules():
    """(team, season, week) -> {pts, opp_pts, starter_pid, starter_name}."""
    out = {}
    with open(os.path.join(SCRATCH, "schedules.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("game_type") != "REG":
                continue
            season, week = int(r["season"]), int(r["week"])
            for side, tm, opp, pts, qid, qn in (
                    ("home", r["home_team"], r["away_team"], r["home_score"],
                     r["home_qb_id"], r["home_qb_name"]),
                    ("away", r["away_team"], r["home_team"], r["away_score"],
                     r["away_qb_id"], r["away_qb_name"])):
                if not pts:
                    continue
                out[(tm, season, week)] = {
                    "pts": int(pts), "opp": opp,
                    "starter_pid": (qid or "").strip(),
                    "starter_name": (qn or "").strip(),
                }
    return out


def main():
    print("loading...", flush=True)
    qbgames = load_qb_games()
    sched = load_schedules()
    print(f"  qb-games: {len(qbgames)}, team-games: {len(sched)}", flush=True)

    # Per-QB chronological game lists for rating computation.
    by_qb = defaultdict(list)
    for g in qbgames:
        by_qb[g["pid"]].append(g)

    # Rating state per QB: (rating, current block of adj values, games played)
    state = {}

    def rating_before(pid):
        st = state.get(pid)
        return st[0] if st else 0.0

    def games_played(pid):
        st = state.get(pid)
        return st[2] if st else 0

    # Per-team trailing structures (chronological global processing).
    team_pts = defaultdict(deque)      # points scored, trailing
    team_starters = defaultdict(deque)  # starter pids, trailing
    team_allowed = defaultdict(deque)   # VALUE allowed per game, trailing

    # QB att lookup for "did the modal starter play" check.
    att_by_game = defaultdict(dict)  # (team,season,week) -> {pid: att}
    for g in qbgames:
        att_by_game[(g["team"], g["season"], g["week"])][g["pid"]] = g["att"]

    # Defense allowed per team-game: sum of opposing QBs' raw VALUE.
    allowed_by_game = defaultdict(float)
    for g in qbgames:
        allowed_by_game[(g["opp"], g["season"], g["week"])] += g["value_raw"]

    results = {"fit": [], "eval": []}

    # Global chronological order; group by (season, week).
    weeks = defaultdict(list)
    for g in qbgames:
        weeks[(g["season"], g["week"])].append(g)
    sched_weeks = defaultdict(list)
    for (tm, season, week), info in sched.items():
        sched_weeks[(season, week)].append((tm, info))

    for sw in sorted(set(weeks) | set(sched_weeks)):
        season, week = sw
        # 1) compute defense adjustments + ratings for this week's QB games
        #    using ONLY prior state.
        for g in weeks.get(sw, []):
            opp = g["opp"]
            oa = team_allowed[opp]
            if len(oa) >= 5:
                opp_avg = sum(oa) / len(oa)
                lg_avg = (sum(sum(v) / len(v) for v in team_allowed.values()
                                if len(v) >= 5)
                          / max(1, sum(1 for v in team_allowed.values()
                                      if len(v) >= 5)))
                g["value_adj"] = g["value_raw"] - (opp_avg - lg_avg)
            else:
                g["value_adj"] = g["value_raw"]
            g["rating_before"] = rating_before(g["pid"])
            g["gp_before"] = games_played(g["pid"])
        # 2) backup-start analysis for this week's team games (prior state).
        for tm, info in sched_weeks.get(sw, []):
            starters = team_starters[tm]
            pts_hist = team_pts[tm]
            if len(starters) >= 5 and len(pts_hist) >= MIN_TRAIL_PTS:
                modal = max(set(starters), key=list(starters).count)
                if info["starter_pid"] and info["starter_pid"] != modal:
                    # clean backup start? modal starter did not play
                    attmap = att_by_game.get((tm, season, week), {})
                    if attmap.get(modal, 0) < 5:
                        resid = info["pts"] - sum(pts_hist) / len(pts_hist)
                        gap = rating_before(info["starter_pid"]) - rating_before(modal)
                        rec = {"season": season, "week": week, "team": tm,
                               "resid": resid, "gap": gap,
                               "starter": info["starter_name"],
                               "gp_starter": games_played(info["starter_pid"]),
                               "gp_modal": games_played(modal)}
                        key = "fit" if season in FIT else ("eval" if season in EVAL else None)
                        if key and not (os.environ.get("QB_STUDY_NOWK1") and week == 1):
                            results[key].append(rec)
        # 3) advance state with this week's completed games.
        for g in weeks.get(sw, []):
            st = state.get(g["pid"], [0.0, [], 0])
            st[1].append(g["value_adj"])
            st[2] += 1
            if len(st[1]) >= BLOCK:
                st[0] = 0.9 * st[0] + 0.1 * (sum(st[1]) / len(st[1]))
                st[1] = []
            state[g["pid"]] = st
        for tm, info in sched_weeks.get(sw, []):
            team_pts[tm].append(info["pts"])
            if len(team_pts[tm]) > TRAIL_TEAM:
                team_pts[tm].popleft()
            if info["starter_pid"]:
                team_starters[tm].append(info["starter_pid"])
                if len(team_starters[tm]) > TRAIL_TEAM:
                    team_starters[tm].popleft()
        for (tm2, s2, w2), allowed in allowed_by_game.items():
            if (s2, w2) == sw:
                dq = team_allowed[tm2]
                dq.append(allowed)
                if len(dq) > TRAIL_DEF:
                    dq.popleft()

    def ols(recs):
        n = len(recs)
        mx = sum(r["gap"] for r in recs) / n
        my = sum(r["resid"] for r in recs) / n
        sxx = sum((r["gap"] - mx) ** 2 for r in recs)
        sxy = sum((r["gap"] - mx) * (r["resid"] - my) for r in recs)
        slope = sxy / sxx if sxx > 1e-9 else 0.0
        return slope, my - slope * mx, my, n

    fit = results["fit"]
    ev = results["eval"]
    slope, icept, const, nfit = ols(fit)
    print(f"FIT n={nfit}: slope={slope:.4f} pts/VALUE, intercept={icept:.3f}, "
          f"mean_resid={const:.3f}", flush=True)
    # Quintile check: mean residual by gap quintile (linearity sanity).
    qs = sorted(fit, key=lambda r: r["gap"])
    qn = max(1, len(qs) // 5)
    for i in range(5):
        chunk = qs[i * qn:(i + 1) * qn] if i < 4 else qs[4 * qn:]
        if chunk:
            print(f"  gap_q{i+1}: n={len(chunk)} gap_mean={sum(r['gap'] for r in chunk)/len(chunk):.1f} "
                  f"resid_mean={sum(r['resid'] for r in chunk)/len(chunk):.2f}", flush=True)
    json.dump({"fit": fit, "eval": ev},
              open(os.path.join(SCRATCH, "qb_study_records.json"), "w"))

    def mse(recs, pred):
        return sum((r["resid"] - pred(r)) ** 2 for r in recs) / len(recs)

    variants = {
        "no_adjustment": lambda r: 0.0,
        "declared_-3.0": lambda r: -3.0,
        "calibrated_constant": lambda r: const,
        "per_qb_value": lambda r: icept + slope * r["gap"],
    }
    out = {"fit": {"n": nfit, "slope": slope, "intercept": icept,
                   "mean_resid": const,
                   "gap_mean": sum(r["gap"] for r in fit) / nfit,
                   "gap_sd": statistics.pstdev([r["gap"] for r in fit]),
                   "resid_sd": statistics.pstdev([r["resid"] for r in fit])},
           "eval": {"n": len(ev)}}
    print(f"EVAL n={len(ev)}", flush=True)
    for name, fn in variants.items():
        m = mse(ev, fn)
        out["eval"][name + "_mse"] = m
        print(f"  {name}: MSE={m:.4f}", flush=True)
    # both-rated subset (gp>=10 for starter and modal)
    ev_rated = [r for r in ev if r["gp_starter"] >= 10 and r["gp_modal"] >= 10]
    out["eval"]["n_both_rated"] = len(ev_rated)
    print(f"  both-rated subset n={len(ev_rated)}", flush=True)
    for name, fn in variants.items():
        m = mse(ev_rated, fn)
        out["eval"]["rated_" + name + "_mse"] = m
        print(f"    {name}: MSE={m:.4f}", flush=True)

    with open(os.path.join(SCRATCH, "qb_study_results.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print("wrote qb_study_results.json", flush=True)


if __name__ == "__main__":
    main()
