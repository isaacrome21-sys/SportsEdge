#!/usr/bin/env python3
"""
NFL_ANCHORED_RATINGS_V1 - design-data viability screen (screens of DESIGN
section 3.2), executed exactly as specified in
engine_constructions_20261026/DESIGN_nfl_sides_totals_replacement.md plus the
band guards stated in PR #2809 (min n=20 per band; a missing/insufficient band
yields FAILED_SCREEN rather than an inferred pass).

DESIGN DATA ONLY - ZERO VALIDATION CREDIT. verified_clv=false, counted_rows=0.
The nflverse closing snapshot is the design baseline (no quote timestamps;
vs-close is never verified CLV).

Implementation notes (all disclosed in the report):
- Ratings core (design 2.2): iterative opponent-adjusted off/def fit in points,
  ridge prior P0=4 pseudo-games at the prior season's final ratings (league mean
  when none), league level L = mean points per team-game over the window
  (prior season + current-season games strictly before the prediction week).
  Ratings refit once per week; same-week games never enter their own fit.
- HFA: single constant fitted on pooled 2019-2025 REG home residuals (design
  fit, as the design prescribes constants are fitted on design data).
- QB term (design 2.4): class of each team's starter vs its previous game's
  starter, from nflverse qb ids. STARTER=0 reference; BACKUP_WITH_PRIOR_STARTS;
  BACKUP_NO_PRIOR_STARTS (rookie-first-start is indistinguishable from this
  class in games.csv, disclosed). Class values fitted by OLS on pooled
  walk-forward margin residuals, bounded |delta| <= 4.0.
- Rest term: beta_rest fitted by OLS on pooled walk-forward margin residuals,
  applied clip(beta*rest_diff, -1, +1) to the margin (half each side).
- Weather (totals only): outdoor games (roof == 'outdoors'), classes wind>=15
  and temp<=32F, constants fitted by OLS on pooled walk-forward total
  residuals, summed, capped |adj| <= 2.0.
- Eligibility (design 2.2): both teams >= 3 prior REG games in the window,
  where a prior-season final rating counts toward the window via its P0
  pseudo-games only if the team also has >= 1 current-season prior game
  (Week 1 is never priced). Implemented as: current-season prior games >= 3,
  OR (prior-season rating exists AND current-season prior games >= 1).
- Anchoring (design 3.1): anchored = line + 0.15 * clamp(raw - line, -4, +4).
- Sigma (design 2.5): fitted on the walk-forward anchored residuals, floored
  at 12.5 per market.
- Stated cover probability (design 2 shape): Phi(|anchored-line| / sigma_fit)
  on the model's favoured side. Bands are on the capped raw disagreement
  |clamp(raw-line, -4, +4)| in {0-1, 1-2, 2-3, 3-4} (the 4+ band is unreachable
  under the cap; #2809's guard treats an unpopulated proposed band as a fail,
  reported as such).
- Screens (design 3.2), per market:
  1. anchored MAE <= close MAE;
  2. no band with n >= 100 overstates realized cover by > 7.5 pp;
  3. realized cover non-decreasing across bands.
"""
import json, math, sys
import numpy as np
import pandas as pd
from scipy.stats import norm

W, C, P0 = 0.15, 4.0, 4
SIGMA_FLOOR = 12.5

def fit_ratings(games, prior, L, hfa, iters=200, tol=1e-9):
    """games: list of (home, away, hs, as_). prior: {team: (off, def)} deviations.
    Returns {team: (off, def)} deviations from L. def is points-allowed terms."""
    teams = sorted({g[0] for g in games} | {g[1] for g in games} | set(prior))
    off = {t: prior.get(t, (0.0, 0.0))[0] for t in teams}
    dfn = {t: prior.get(t, (0.0, 0.0))[1] for t in teams}
    poff = {t: prior.get(t, (0.0, 0.0))[0] for t in teams}
    pdfn = {t: prior.get(t, (0.0, 0.0))[1] for t in teams}
    for _ in range(iters):
        no, nd = {}, {}
        for t in teams:
            o_num, o_den, d_num, d_den = P0 * poff[t], P0, P0 * pdfn[t], P0
            for (h, a, hs, as_) in games:
                if h == t:  # t home: its offence produced hs vs a's defence
                    o_num += hs - L - dfn[a] - hfa / 2; o_den += 1
                    d_num += as_ - L - off[a] + hfa / 2; d_den += 1
                elif a == t:
                    o_num += as_ - L - dfn[h] + hfa / 2; o_den += 1
                    d_num += hs - L - off[h] - hfa / 2; d_den += 1
            no[t], nd[t] = o_num / o_den, d_num / d_den
        shift = max(max(abs(no[t] - off[t]), abs(nd[t] - dfn[t])) for t in teams)
        off, dfn = no, nd
        if shift < tol:
            break
    return {t: (off[t], dfn[t]) for t in teams}

def main(path):
    df = pd.read_csv(path)
    df = df[(df.game_type == "REG") & df.home_score.notna() & df.away_score.notna()]
    df["gameday"] = pd.to_datetime(df.gameday)
    df = df.sort_values(["season", "week", "gameday"]).reset_index(drop=True)

    # ---- HFA design fit: pooled 2019-2025 home margin mean (design constant)
    reg_all = df[df.season.between(2019, 2025)]
    hfa = float((reg_all.home_score - reg_all.away_score).mean())

    seasons = {}
    for s, g in df.groupby("season"):
        seasons[int(s)] = g

    # prior-season final ratings per season
    final_ratings, league_L = {}, {}
    for s in sorted(seasons):
        g = seasons[s]
        games = list(zip(g.home_team, g.away_team, g.home_score, g.away_score))
        L = float(np.mean([*g.home_score, *g.away_score]))
        league_L[s] = L
        prior = final_ratings.get(s - 1, {})
        final_ratings[s] = fit_ratings(games, prior, L, hfa)

    # QB start history (career starts before each game) + previous starter
    starts_count = {}   # qb_id -> starts before current game (updated after)
    last_qb = {}        # team -> qb_id of previous game
    qb_class = {}       # row idx -> (away_class, home_class)
    for idx, r in df.iterrows():
        row = {}
        for side in ("away", "home"):
            team, qb = r[f"{side}_team"], r[f"{side}_qb_id"]
            if last_qb.get(team) == qb:
                cls = "STARTER"
            elif starts_count.get(qb, 0) >= 1:
                cls = "BACKUP_WITH_PRIOR_STARTS"
            else:
                cls = "BACKUP_NO_PRIOR_STARTS"
            row[side] = cls
        qb_class[idx] = (row["away"], row["home"])
        for side in ("away", "home"):
            last_qb[r[f"{side}_team"]] = r[f"{side}_qb_id"]
            starts_count[r[f"{side}_qb_id"]] = starts_count.get(r[f"{side}_qb_id"], 0) + 1

    # ---- walk-forward predictions 2020-2025
    preds = []
    for s in range(2020, 2026):
        g = seasons[s]
        prior = final_ratings.get(s - 1, {})
        prior_L = league_L.get(s - 1, league_L[s])
        played = []           # current-season games so far
        team_games = {}
        for wk, wg in g.groupby("week"):
            window = list(zip(
                seasons[s - 1].home_team, seasons[s - 1].away_team,
                seasons[s - 1].home_score, seasons[s - 1].away_score)) + played \
                if s - 1 in seasons else played
            pts = [x[2] for x in window] + [x[3] for x in window]
            L = float(np.mean(pts)) if pts else prior_L
            ratings = fit_ratings(window, prior, L, hfa) if window else prior
            for idx, r in wg.iterrows():
                h, a = r.home_team, r.away_team
                elig = all(
                    team_games.get(t, 0) >= 3 or
                    (t in prior and team_games.get(t, 0) >= 1)
                    for t in (h, a))
                if h not in ratings or a not in ratings:
                    elig = False
                if not elig:
                    continue
                neut = str(r.location).strip().lower() == "neutral"
                hf = 0.0 if neut else hfa
                oh, dh = ratings[h]; oa, da = ratings[a]
                mu_h = L + oh + da + hf / 2
                mu_a = L + oa + dh - hf / 2
                preds.append(dict(
                    idx=idx, season=s, week=int(r.week), home=h, away=a,
                    hs=r.home_score, as_=r.away_score,
                    mu_h=mu_h, mu_a=mu_a,
                    spread_line=r.spread_line, total_line=r.total_line,
                    home_rest=r.home_rest, away_rest=r.away_rest,
                    roof=r.roof, temp=r.temp, wind=r.wind,
                    qb_h=qb_class[idx][1], qb_a=qb_class[idx][0]))
            for _, r in wg.iterrows():
                played.append((r.home_team, r.away_team, r.home_score, r.away_score))
                team_games[r.home_team] = team_games.get(r.home_team, 0) + 1
                team_games[r.away_team] = team_games.get(r.away_team, 0) + 1

    p = pd.DataFrame(preds)
    p["margin"] = p.hs - p.as_
    p["total"] = p.hs + p.as_
    p["raw_margin"] = p.mu_h - p.mu_a
    p["raw_total0"] = p.mu_h + p.mu_a

    # ---- fit QB / rest / weather constants on pooled walk-forward residuals
    res_m = p.margin - p.raw_margin
    X = pd.DataFrame({
        "qb_h_prior": (p.qb_h == "BACKUP_WITH_PRIOR_STARTS").astype(float),
        "qb_h_none": (p.qb_h == "BACKUP_NO_PRIOR_STARTS").astype(float),
        "qb_a_prior": (p.qb_a == "BACKUP_WITH_PRIOR_STARTS").astype(float),
        "qb_a_none": (p.qb_a == "BACKUP_NO_PRIOR_STARTS").astype(float),
        "rest_diff_raw": (p.home_rest - p.away_rest).astype(float),
    })
    beta, *_ = np.linalg.lstsq(X.values, res_m.values, rcond=None)
    qb_delta = {
        "BACKUP_WITH_PRIOR_STARTS": float(np.clip(beta[0], -4, 4)),
        "BACKUP_NO_PRIOR_STARTS": float(np.clip(beta[1], -4, 4)),
    }
    # away QB effect enters with opposite sign on margin: fitted coefs beta[2], beta[3]
    qb_delta_away = {
        "BACKUP_WITH_PRIOR_STARTS": float(np.clip(beta[2], -4, 4)),
        "BACKUP_NO_PRIOR_STARTS": float(np.clip(beta[3], -4, 4)),
    }
    beta_rest = float(beta[4])

    res_t = p.total - p.raw_total0
    outd = (p.roof == "outdoors")
    Xw = pd.DataFrame({
        "wind15": (outd & (p.wind >= 15)).astype(float),
        "cold32": (outd & (p.temp <= 32)).astype(float),
    })
    bw, *_ = np.linalg.lstsq(Xw.values, res_t.values, rcond=None)
    w_wind, w_cold = float(bw[0]), float(bw[1])

    def qb_adj(cls, table):
        return table.get(cls, 0.0)

    p["mu_h2"] = p.mu_h + [qb_adj(c, qb_delta) for c in p.qb_h]
    # away coefficients were fitted directly on margin (home-away); a worse
    # away QB raises margin. Away mean shift = -coef.
    p["mu_a2"] = p.mu_a - [qb_adj(c, qb_delta_away) for c in p.qb_a]
    p["raw_margin2"] = p.mu_h2 - p.mu_a2
    rest_term = np.clip(beta_rest * (p.home_rest - p.away_rest), -1, 1)
    p["raw_margin2"] = p.raw_margin2 + rest_term
    wadj = np.where(outd & (p.wind >= 15), w_wind, 0.0) + np.where(outd & (p.temp <= 32), w_cold, 0.0)
    p["raw_total"] = p.raw_total0 + np.clip(wadj, -2, 2)

    out = {"hfa_fitted": hfa, "beta_rest_fitted": beta_rest,
           "qb_delta_home": qb_delta, "qb_delta_away_margin_coef": qb_delta_away,
           "weather": {"wind_ge_15": w_wind, "temp_le_32": w_cold},
           "n_predictions": int(len(p)),
           "seasons": [int(x) for x in sorted(p.season.unique())],
           "markets": {}}

    for mkt, raw_col, line_col, actual_col in (
            ("spread", "raw_margin2", "spread_line", "margin"),
            ("total", "raw_total", "total_line", "total")):
        d = p.dropna(subset=[line_col]).copy()
        d["dev_raw"] = d[raw_col] - d[line_col]
        d["dev_cap"] = d.dev_raw.clip(-C, C)
        d["anchored"] = d[line_col] + W * d.dev_cap
        d["err_close"] = (d[line_col] - d[actual_col]).abs()
        d["err_anch"] = (d.anchored - d[actual_col]).abs()
        d["err_raw"] = (d[raw_col] - d[actual_col]).abs()
        resid = d.anchored - d[actual_col]
        sigma = max(float(resid.std(ddof=1)), SIGMA_FLOOR)
        d["abs_band_dev"] = d.dev_cap.abs()
        d["band"] = pd.cut(d.abs_band_dev, [-0.001, 1, 2, 3, 4.0001],
                           labels=["0-1", "1-2", "2-3", "3-4"])
        # favoured side: model says actual beats line in direction of dev_cap
        if mkt == "spread":
            # nflverse spread_line is in home-margin units (positive = home
            # favoured; verified empirically: MAE |result - spread| = 10.24 vs
            # 14.67 for the opposite convention). Home covers iff
            # margin > spread_line.
            d["fav_covers"] = np.where(
                d.dev_cap > 0, d.margin - d.spread_line > 0,
                np.where(d.dev_cap < 0, d.margin - d.spread_line < 0, np.nan))
            d["fav_push"] = (d.margin - d.spread_line == 0)
        else:
            d["fav_covers"] = np.where(
                d.dev_cap > 0, d.total > d.total_line,
                np.where(d.dev_cap < 0, d.total < d.total_line, np.nan))
            d["fav_push"] = (d.total == d.total_line)
        d.loc[d.fav_push, "fav_covers"] = np.nan
        d["stated"] = norm.cdf(d.dev_cap.abs() * W / sigma)
        bands = []
        for b in ["0-1", "1-2", "2-3", "3-4"]:
            bd = d[d.band == b]
            cov = bd.fav_covers.dropna()
            bands.append({
                "band": b, "n": int(len(bd)), "n_graded": int(len(cov)),
                "mean_stated": float(bd.stated.mean()) if len(bd) else None,
                "realized_cover": float(cov.mean()) if len(cov) else None,
                "overstate_pp": (float(bd.stated.mean() - cov.mean()) * 100)
                if len(cov) else None})
        graded = [b for b in bands if b["n"] >= 20]
        s1 = bool(d.err_anch.mean() <= d.err_close.mean())
        s2 = all(b["overstate_pp"] is not None and b["overstate_pp"] <= 7.5
                 for b in bands if b["n"] >= 100)
        rc = [b["realized_cover"] for b in bands if b["n"] >= 20]
        s3_bands_ok = len(graded) == 4
        s3 = s3_bands_ok and all(rc[i] <= rc[i + 1] + 1e-12 for i in range(len(rc) - 1))
        out["markets"][mkt] = {
            "n": int(len(d)), "sigma_fitted": sigma,
            "mae_close": float(d.err_close.mean()),
            "mae_raw": float(d.err_raw.mean()),
            "mae_anchored": float(d.err_anch.mean()),
            "bands": bands,
            "screen1_mae_pass": s1, "screen2_calibration_pass": bool(s2),
            "screen3_rising_cover_pass": bool(s3),
            "screen3_note": ("all 4 bands populated n>=20" if s3_bands_ok
                             else "MISSING/INSUFFICIENT BAND -> fail per #2809 guard"),
            "verdict": "PASS_TO_PREREG_SCREEN" if (s1 and s2 and s3) else "FAILED_SCREEN",
        }
    print(json.dumps(out, indent=1))
    p.to_csv("/tmp/bt568/nfl_nar_preds.csv", index=False)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bt568/games.csv")
