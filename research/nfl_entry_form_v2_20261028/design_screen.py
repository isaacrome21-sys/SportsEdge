"""NFL_ENTRY_FORM_V2 — design screens on 2020-2025 DESIGN data.

DESIGN EVIDENCE ONLY. Seasons 2020-2025 were seen by the retired
NFL_ANCHORED_RATINGS_V1 (closed FAILED_SCREEN, PR #2809) and by the Oct 27,
2026 re-execution (draft PR #2833). Nothing produced here is validation,
opens a clock, starts a count, or supports a verified claim. The market
baseline is the nflverse closing snapshot (vs-close; never verified CLV).
2026 rows are never touched: the 2026 remainder is the preregistration
draft's validation split, and screening on it would convert it to design
data.

Screens executed (all walk-forward: coefficients fitted on seasons strictly
before the test season; every feature uses games strictly before the target
game; test seasons 2021-2025, training starts with 2020):

  1. Standalone current-form EPA core (ablations A/B/C) vs the close.
  2. Close-residual context model (ablations A/B/C) vs the close.
  3. Targeted probes: QB-change subset; dual-signal agreement gate + bands.

Data (pins in PINS.json beside this file):
  * nflverse games.csv.gz — the hash-pinned file from draft PR #2831
    (research/nfl_cfb_design_baselines_20261027/); pass --games if the pin
    lives elsewhere. sha256 is verified before use; mismatch = refuse.
  * nflverse stats_team / stats_player weekly parquets 2020-2025 —
    downloaded from nflverse-data GitHub releases into --data-dir and
    sha256-verified against the pinned values; mismatch = refuse.

Sign convention (verified empirically in this run, and reconciled against
the program's known close MAE of ~9.80): nflverse `spread_line` IS the
market's home-margin estimate (MAE(margin vs +spread_line) = 9.76 on
2020-2025 REG; the negated reading gives 14.26 and is wrong). An early
prototype run with the negated convention produced impossible results
(model "beating" the close by 3.7 pts, +57% ROI) and was discarded in
full; only corrected-convention numbers are reported.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import urllib.request

import numpy as np
import pandas as pd

SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
PRIOR_PLAYS = 250.0        # shrinkage prior (plays) for EPA rates
PRIOR_QB_ATT = 200.0       # shrinkage prior (attempts) for QB EPA
CARRY = 0.30               # prior-season carry weight, team EPA sums
QB_CARRY = 0.50            # prior-season carry weight, QB EPA sums
MIN_PRIOR_GAMES = 3        # eligibility gate (both teams, in-season)

GAMES_SHA256 = "82b05d7096b3f59acd127da8762b1e2260f4af70b49e5548ce4cd3ade92a49a5"
PARQUET_PINS = {
    "stats_team_week_2020.parquet": "a310b8ad8c70240152f08cf936210317b90280cb1cc51383735d280c2fb7f4ec",
    "stats_team_week_2021.parquet": "d7c1bc5f00e5fae933e6ba6716f0687289aea0ae71a6b36ddd3822ca3f3f54aa",
    "stats_team_week_2022.parquet": "646493a539f2cb3fd2f593902cd733fc168dd6b16ec4be9b77a03bd2720cde3e",
    "stats_team_week_2023.parquet": "a155e2a9cb2a6bff1b254f747a33603c43aa5a1117c26d203b44e5bfb83339b1",
    "stats_team_week_2024.parquet": "c95aca86417589edb34b5001c11ba4bab869394fd3d51e475ff0958dda1669fc",
    "stats_team_week_2025.parquet": "ec168d98ebbcb0d14d1049ba690e55a629fe6e4f00aaa8a700c309d9dad6d34d",
    "stats_player_week_2020.parquet": "e788d88318a6e99b8005c1c9814423d05bb91f757d5d977d3280f2eb83927b23",
    "stats_player_week_2021.parquet": "2c6894499e96dcf20b060969c607a0ff4e2018f369efad6e97d88abbe77b7277",
    "stats_player_week_2022.parquet": "64c1684938b029d68e33d7852cbee918266c8ac7f30b4c097c0a8912b4384e52",
    "stats_player_week_2023.parquet": "ac776fbd7c9fefdb4069b72304f4c5fa05ae417acd49f6e4e27be14b9d7a4bbc",
    "stats_player_week_2024.parquet": "847569d194ca3d96b5efcf91e6eac5e18780fc47568a713fd545a82d29d155c1",
    "stats_player_week_2025.parquet": "2a461becaa9adb3c93a3074a3a31f1e960162a50163371a2d34e28393b5fff10",
}
RELEASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/{tag}/{name}"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_parquets(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    for name, pin in PARQUET_PINS.items():
        path = os.path.join(data_dir, name)
        if not os.path.exists(path):
            tag = "stats_team" if name.startswith("stats_team") else "stats_player"
            urllib.request.urlretrieve(RELEASE_URL.format(tag=tag, name=name), path)
        got = sha256_file(path)
        if got != pin:
            raise SystemExit(f"PIN MISMATCH {name}: got {got}, want {pin} — refusing")


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def load_games(path):
    if sha256_file(path) != GAMES_SHA256:
        raise SystemExit("games.csv.gz sha256 does not match the PR #2831 pin — refusing")
    with gzip.open(path, "rt") as fh:
        g = pd.read_csv(fh)
    g = g[(g.game_type == "REG") & g.season.isin(SEASONS)]
    g = g.dropna(subset=["spread_line", "total_line", "home_score", "away_score"])
    g = g.sort_values(["season", "week", "gameday"]).reset_index(drop=True)
    g["margin"] = g.home_score - g.away_score
    g["total"] = g.home_score + g.away_score
    g["mkt_margin"] = g.spread_line   # verified home-margin units (see header)
    g["mkt_total"] = g.total_line
    return g


def load_team_week(data_dir):
    frames = []
    for s in SEASONS:
        df = pd.read_parquet(os.path.join(data_dir, f"stats_team_week_{s}.parquet"))
        frames.append(df[df.season_type == "REG"].copy())
    tw = pd.concat(frames, ignore_index=True)
    tw["plays"] = tw.attempts + tw.sacks_suffered + tw.carries
    tw["epa_sum"] = tw.passing_epa + tw.rushing_epa
    tw["off_epa"] = tw.epa_sum / tw.plays
    opp = tw[["game_id", "team", "off_epa", "plays"]].rename(
        columns={"team": "opponent_team", "off_epa": "opp_off_epa", "plays": "opp_plays"})
    tw = tw.merge(opp, on=["game_id", "opponent_team"], how="left")
    tw["def_epa"] = tw.opp_off_epa
    return tw[["season", "week", "team", "game_id", "plays", "epa_sum",
               "off_epa", "def_epa"]]


def load_qb_week(data_dir):
    frames = []
    for s in SEASONS:
        df = pd.read_parquet(os.path.join(data_dir, f"stats_player_week_{s}.parquet"))
        frames.append(df[df.position == "QB"].copy())
    qw = pd.concat(frames, ignore_index=True)
    qw["qb_epa_sum"] = qw.passing_epa.fillna(0) + qw.rushing_epa.fillna(0)
    return qw[["season", "week", "team", "player_id", "attempts", "qb_epa_sum"]]


class RateBook:
    """Shrunk cumulative EPA sums with prior-season carry."""

    def __init__(self):
        self.agg = {}

    def roll_season(self, prior_final):
        self.agg = {}
        for team, st in prior_final.items():
            self.agg[team] = {
                "off_epa": st["off_epa"] * CARRY, "plays": st["plays"] * CARRY,
                "def_epa": st["def_epa"] * CARRY, "def_plays": st["def_plays"] * CARRY,
                "games": 0, "hist": [],
            }

    def ensure(self, team):
        if team not in self.agg:
            self.agg[team] = {"off_epa": 0.0, "plays": 0.0, "def_epa": 0.0,
                              "def_plays": 0.0, "games": 0, "hist": []}
        return self.agg[team]

    @staticmethod
    def _rate(epa, plays):
        return epa / (plays + PRIOR_PLAYS)

    def rates(self, team):
        st = self.ensure(team)
        return (self._rate(st["off_epa"], st["plays"]),
                self._rate(st["def_epa"], st["def_plays"]),
                st["plays"] / max(st["games"], 1) if st["games"] else 62.0,
                st["games"])

    def form_rates(self, team, k=4):
        st = self.ensure(team)
        hist = st["hist"][-k:]
        if not hist:
            return self.rates(team)[:2]
        oe = sum(h[0] for h in hist); pl = sum(h[1] for h in hist)
        de = sum(h[2] for h in hist); dp = sum(h[3] for h in hist)
        so, sd, _, _ = self.rates(team)
        return ((oe + 150.0 * so) / (pl + 150.0),
                (de + 150.0 * sd) / (dp + 150.0))

    def add(self, team, off_epa_sum, plays, def_epa_sum, def_plays):
        st = self.ensure(team)
        st["off_epa"] += off_epa_sum; st["plays"] += plays
        st["def_epa"] += def_epa_sum; st["def_plays"] += def_plays
        st["games"] += 1
        st["hist"].append((off_epa_sum, plays, def_epa_sum, def_plays))

    def final(self):
        return {t: dict(st) for t, st in self.agg.items()}


def build_features(games, tw, qw):
    """Walk forward game by game; one feature row per eligible game."""
    tw_by_game = {}
    for row in tw.itertuples(index=False):
        tw_by_game.setdefault(row.game_id, {})[row.team] = row
    qb_rows = {}
    for row in qw.itertuples(index=False):
        qb_rows.setdefault((row.season, row.week, row.team), {})[row.player_id] = (
            row.attempts, row.qb_epa_sum)

    book = RateBook()
    qb_book = {}
    qb_carry = {}
    team_qb = {}
    prev_starter = {}
    out = []
    cur_season = None
    prior_final = {}
    for gm in games.itertuples(index=False):
        if gm.season != cur_season:
            if cur_season is not None:
                prior_final = book.final()
                for pid, v in qb_book.items():
                    qb_carry[pid] = [v[0] * QB_CARRY, v[1] * QB_CARRY]
            book.roll_season(prior_final)
            qb_book = {k: list(v) for k, v in qb_carry.items()}
            team_qb = {}
            prev_starter = {}
            cur_season = gm.season
        h, a = gm.home_team, gm.away_team
        oh, dh, plh, ngh = book.rates(h)
        oa, da, pla, nga = book.rates(a)
        foh, fdh = book.form_rates(h)
        foa, fda = book.form_rates(a)

        def pts(off, dfn, plays):
            return (off - dfn) * plays

        exp_h = pts(oh, da, plh); exp_a = pts(oa, dh, pla)
        fexp_h = pts(foh, fda, plh); fexp_a = pts(foa, fdh, pla)

        def qb_delta(team, starter_id):
            if starter_id is None or (isinstance(starter_id, float)
                                      and math.isnan(starter_id)):
                return 0.0, 0
            se, sa = qb_book.get(starter_id, [0.0, 0.0])
            starter_rate = se / (sa + PRIOR_QB_ATT)
            te, ta = team_qb.get(team, [0.0, 0.0])
            team_rate = te / (ta + PRIOR_QB_ATT)
            chg = 1 if prev_starter.get(team) not in (None, starter_id) else 0
            return (starter_rate - team_rate) * 36.0, chg

        qh, chg_h = qb_delta(h, gm.home_qb_id)
        qa, chg_a = qb_delta(a, gm.away_qb_id)
        outdoor = 1 if str(gm.roof).lower() in ("outdoors", "open") else 0
        wind = gm.wind if not (isinstance(gm.wind, float) and math.isnan(gm.wind)) else 0.0
        temp = gm.temp if not (isinstance(gm.temp, float) and math.isnan(gm.temp)) else 55.0
        if ngh >= MIN_PRIOR_GAMES and nga >= MIN_PRIOR_GAMES:
            out.append({
                "game_id": gm.game_id, "season": gm.season, "week": gm.week,
                "margin": gm.margin, "total": gm.total,
                "mkt_margin": gm.mkt_margin, "mkt_total": gm.mkt_total,
                "x_epa_margin": exp_h - exp_a,
                "x_form_margin": (fexp_h - fexp_a) - (exp_h - exp_a),
                "x_qb_h": qh, "x_qb_a": -qa,
                "x_rest": (gm.home_rest or 0) - (gm.away_rest or 0),
                "y_epa_total": exp_h + exp_a,
                "y_form_total": (fexp_h + fexp_a) - (exp_h + exp_a),
                "y_pace": plh + pla,
                "y_wind": -max(0.0, wind - 12.0) * outdoor,
                "y_cold": -max(0.0, 32.0 - temp) / 10.0 * outdoor,
                "qb_chg": chg_h + chg_a,
            })
        rows = tw_by_game.get(gm.game_id, {})
        for team in (h, a):
            r = rows.get(team)
            if r is not None:
                orow = rows.get(a if team == h else h)
                book.add(team, r.epa_sum, r.plays,
                         orow.epa_sum if orow is not None else 0.0,
                         orow.plays if orow is not None else 0.0)
            for pid, (att, esum) in qb_rows.get((gm.season, gm.week, team), {}).items():
                if att and att > 0:
                    cur = qb_book.setdefault(pid, [0.0, 0.0])
                    cur[0] += esum; cur[1] += att
                    tq = team_qb.setdefault(team, [0.0, 0.0])
                    tq[0] += esum; tq[1] += att
        prev_starter[h] = gm.home_qb_id
        prev_starter[a] = gm.away_qb_id
    feat = pd.DataFrame(out)
    feat["y_pace_dev"] = feat.y_pace - 124.0
    return feat


def fit_ols(X, y):
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    return beta, float(np.std(resid, ddof=len(beta)))


def predict(beta, X):
    return np.column_stack([np.ones(len(X)), X]) @ beta


def ca_trend_p(ns, covers, scores):
    """One-sided Cochran-Armitage trend test (normal approx), H1: increasing."""
    ns = np.asarray(ns, float); covers = np.asarray(covers, float)
    scores = np.asarray(scores, float)
    n_tot = ns.sum(); p = covers.sum() / n_tot
    xbar = (ns * scores).sum() / n_tot
    num = (scores * (covers - ns * p)).sum()
    var = p * (1 - p) * (ns * (scores - xbar) ** 2).sum()
    if var <= 0:
        return 1.0
    z = num / math.sqrt(var)
    return 0.5 * (1 - math.erf(z / math.sqrt(2)))


BANDS = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.5), (3.5, 5.0), (5.0, 99.0)]


def band_table(d, win):
    rows = []
    for lo, hi in BANDS:
        m = (np.abs(d) >= lo) & (np.abs(d) < hi)
        n = int(m.sum())
        rows.append({"band": f"{lo}-{hi if hi < 90 else '+'}", "n": n,
                     "cover": float(win[m].mean()) if n else None})
    ns = [r["n"] for r in rows]
    cv = [(r["cover"] or 0) * r["n"] for r in rows]
    return rows, (ca_trend_p(ns, cv, [0, 1, 2, 3, 4]) if sum(ns) else 1.0)


def roi_flat(win, push):
    w = float(win.sum()); l = float((1 - win - push).sum())
    if w + l == 0:
        return None
    return float((w * (100.0 / 110.0) - l) / (w + l))


def _cover_frame(te, proj, mktv, actual):
    d = proj - mktv
    diff = actual - mktv
    cs = np.where(d > 0, diff, -diff)
    return d, (cs > 0).astype(float), (cs == 0).astype(float)


def evaluate_core(feat, cols, target, mkt):
    rows = []
    for s in sorted(feat.season.unique()):
        tr = feat[feat.season < s]; te = feat[feat.season == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        beta, sigma = fit_ols(tr[cols].to_numpy(float), tr[target].to_numpy(float))
        proj = predict(beta, te[cols].to_numpy(float))
        mktv = te[mkt].to_numpy(float); actual = te[target].to_numpy(float)
        d, win, push = _cover_frame(te, proj, mktv, actual)
        rows.append(pd.DataFrame({
            "d": d, "win": win, "push": push,
            "mae_model": np.abs(actual - proj), "mae_close": np.abs(actual - mktv),
            "sigma": sigma, "stated": [norm_cdf(x / sigma) for x in np.abs(d)]}))
    P = pd.concat(rows, ignore_index=True)
    bt, trend_p = band_table(P.d.to_numpy(), P.win.to_numpy())
    picks = P[(P.d.abs() >= 2.0) & (P.stated >= 0.545)]
    return {"n_games": int(len(P)), "mae_model": float(P.mae_model.mean()),
            "mae_close": float(P.mae_close.mean()),
            "sigma_train_mean": float(P.sigma.mean()),
            "share_absd_ge2": float((P.d.abs() >= 2.0).mean()),
            "bands": bt, "trend_p": trend_p,
            "picks_|d|>=2,p>=0.545": {
                "n": int(len(picks)),
                "cover": float(picks.win.mean()) if len(picks) else None,
                "roi_flat110": roi_flat(picks.win.to_numpy(), picks.push.to_numpy())
                if len(picks) else None}}


def evaluate_residual(feat, cols, target, mkt):
    feat = feat.assign(resid=(feat[target] - feat[mkt]).to_numpy(float))
    rows = []
    for s in sorted(feat.season.unique()):
        tr = feat[feat.season < s]; te = feat[feat.season == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        beta, sigma = fit_ols(tr[cols].to_numpy(float), tr.resid.to_numpy(float))
        adj = predict(beta, te[cols].to_numpy(float))
        mktv = te[mkt].to_numpy(float); actual = te[target].to_numpy(float)
        d, win, push = _cover_frame(te, mktv + adj, mktv, actual)
        rows.append(pd.DataFrame({
            "d": d, "win": win, "push": push,
            "mae_model": np.abs(actual - (mktv + adj)),
            "mae_close": np.abs(actual - mktv),
            "sigma": sigma, "stated": [norm_cdf(x / sigma) for x in np.abs(d)]}))
    P = pd.concat(rows, ignore_index=True)
    bt, trend_p = band_table(P.d.to_numpy(), P.win.to_numpy())
    out = {"n_games": int(len(P)), "mae_model": float(P.mae_model.mean()),
           "mae_close": float(P.mae_close.mean()),
           "sigma_resid_mean": float(P.sigma.mean()),
           "share_absd_ge2": float((P.d.abs() >= 2.0).mean()),
           "bands": bt, "trend_p": trend_p}
    for gate in (2.0, 1.5):
        picks = P[(P.d.abs() >= gate) & (P.stated >= 0.545)]
        out[f"picks_|d|>={gate},p>=0.545"] = {
            "n": int(len(picks)),
            "cover": float(picks.win.mean()) if len(picks) else None,
            "roi_flat110": roi_flat(picks.win.to_numpy(), picks.push.to_numpy())
            if len(picks) else None}
    return out


def probe_qb_change(feat):
    sub = feat[feat.qb_chg >= 1]
    diff = (sub.margin - sub.mkt_margin).to_numpy(float)
    qb = (sub.x_qb_h + sub.x_qb_a).to_numpy(float)
    cs = np.where(qb > 0, diff, -diff)
    win = (cs > 0).astype(float); push = (cs == 0).astype(float)
    strong = np.abs(qb) >= 2.0
    return {"n_qb_change_games": int(len(sub)),
            "qb_delta_sign_cover_all": float(win.mean()),
            "subset_|qb|>=2": {
                "n": int(strong.sum()),
                "cover": float(win[strong].mean()) if strong.sum() else None,
                "roi_flat110": roi_flat(win[strong], push[strong])
                if strong.sum() else None},
            "corr_qb_delta_vs_close_residual": float(np.corrcoef(qb, diff)[0, 1])}


def probe_agreement(feat, core_cols, res_cols, target, mkt):
    rows = []
    for s in sorted(feat.season.unique()):
        tr = feat[feat.season < s]; te = feat[feat.season == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        beta, sigma = fit_ols(tr[core_cols].to_numpy(float), tr[target].to_numpy(float))
        core = predict(beta, te[core_cols].to_numpy(float))
        b_res, _ = fit_ols(tr[res_cols].to_numpy(float),
                           (tr[target] - tr[mkt]).to_numpy(float))
        adj = predict(b_res, te[res_cols].to_numpy(float))
        rows.append(pd.DataFrame({
            "d": core - te[mkt].to_numpy(float), "adj": adj,
            "diff": te[target].to_numpy(float) - te[mkt].to_numpy(float),
            "sigma": sigma}))
    P = pd.concat(rows, ignore_index=True)
    out = {}
    for gate in (3.0, 5.0):
        m = (np.sign(P.d) == np.sign(P.adj)) & (P.d.abs() >= gate)
        A = P[m]
        cs = np.where(A.d.to_numpy() > 0, A["diff"].to_numpy(), -A["diff"].to_numpy())
        win = (cs > 0).astype(float); push = (cs == 0).astype(float)
        out[f"agree_|d|>={gate}"] = {
            "n": int(len(A)), "cover": float(win.mean()) if len(A) else None,
            "roi_flat110": roi_flat(win, push) if len(A) else None}
    m = (np.sign(P.d) != np.sign(P.adj)) & (P.d.abs() >= 3.0)
    A = P[m]
    cs = np.where(A.d.to_numpy() > 0, A["diff"].to_numpy(), -A["diff"].to_numpy())
    win = (cs > 0).astype(float); push = (cs == 0).astype(float)
    out["disagree_|d|>=3"] = {"n": int(len(A)),
                              "cover": float(win.mean()) if len(A) else None,
                              "roi_flat110": roi_flat(win, push) if len(A) else None}
    # band table on the agreement subset (|d| >= 3): stated vs realized
    m = (np.sign(P.d) == np.sign(P.adj)) & (P.d.abs() >= 3.0)
    A = P[m].copy()
    cs = np.where(A.d.to_numpy() > 0, A["diff"].to_numpy(), -A["diff"].to_numpy())
    A["win"] = (cs > 0).astype(float)
    A["stated"] = [norm_cdf(abs(x) / s) for x, s in zip(A.d, A.sigma)]
    bands = []
    ns, cv = [], []
    for lo, hi in [(3.0, 5.0), (5.0, 7.0), (7.0, 10.0), (10.0, 99.0)]:
        mm = (A.d.abs() >= lo) & (A.d.abs() < hi)
        if mm.sum():
            bands.append({"band": f"{lo}-{hi if hi < 90 else '+'}",
                          "n": int(mm.sum()),
                          "stated": float(A.stated[mm].mean()),
                          "realized": float(A.win[mm].mean()),
                          "overstatement_pp": float(
                              (A.stated[mm].mean() - A.win[mm].mean()) * 100)})
            ns.append(int(mm.sum())); cv.append(float(A.win[mm].sum()))
    out["agreement_bands"] = bands
    out["agreement_trend_p"] = ca_trend_p(ns, cv, [0, 1, 2, 3]) if ns else 1.0
    out["sigma_fit_mean"] = float(A.sigma.mean()) if len(A) else None
    return out


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--games", default=os.path.join(
        here, "..", "nfl_cfb_design_baselines_20261027", "nflverse_games.csv.gz"))
    ap.add_argument("--data-dir", default=os.path.join(here, "data"))
    ap.add_argument("--out", default=os.path.join(here, "screen_results.json"))
    args = ap.parse_args()

    ensure_parquets(args.data_dir)
    games = load_games(args.games)
    feat = build_features(games, load_team_week(args.data_dir),
                          load_qb_week(args.data_dir))
    results = {
        "evidence_state": "DESIGN ONLY — 2020-2025 design data; vs-close; "
                          "never verified CLV; zero validation credit",
        "n_eligible_feature_rows": int(len(feat)),
        "core_margin_A_season_epa": evaluate_core(
            feat, ["x_epa_margin"], "margin", "mkt_margin"),
        "core_margin_B_+form": evaluate_core(
            feat, ["x_epa_margin", "x_form_margin"], "margin", "mkt_margin"),
        "core_margin_C_full": evaluate_core(
            feat, ["x_epa_margin", "x_form_margin", "x_qb_h", "x_qb_a", "x_rest"],
            "margin", "mkt_margin"),
        "core_total_A_season_epa": evaluate_core(
            feat, ["y_epa_total"], "total", "mkt_total"),
        "core_total_B_+form": evaluate_core(
            feat, ["y_epa_total", "y_form_total"], "total", "mkt_total"),
        "core_total_C_full": evaluate_core(
            feat, ["y_epa_total", "y_form_total", "y_pace", "y_wind", "y_cold"],
            "total", "mkt_total"),
        "resid_margin_A_form": evaluate_residual(
            feat, ["x_form_margin"], "margin", "mkt_margin"),
        "resid_margin_B_form+qb": evaluate_residual(
            feat, ["x_form_margin", "x_qb_h", "x_qb_a"], "margin", "mkt_margin"),
        "resid_margin_C_full": evaluate_residual(
            feat, ["x_form_margin", "x_qb_h", "x_qb_a", "x_rest"],
            "margin", "mkt_margin"),
        "resid_total_A_form": evaluate_residual(
            feat, ["y_form_total"], "total", "mkt_total"),
        "resid_total_B_form+pace": evaluate_residual(
            feat, ["y_form_total", "y_pace_dev"], "total", "mkt_total"),
        "resid_total_C_full": evaluate_residual(
            feat, ["y_form_total", "y_pace_dev", "y_wind", "y_cold"],
            "total", "mkt_total"),
        "probe_qb_change": probe_qb_change(feat),
        "probe_agreement_margin": probe_agreement(
            feat, ["x_epa_margin", "x_form_margin"],
            ["x_form_margin", "x_qb_h", "x_qb_a", "x_rest"], "margin", "mkt_margin"),
        "probe_agreement_total": probe_agreement(
            feat, ["y_epa_total", "y_form_total"],
            ["y_form_total", "y_pace_dev", "y_wind", "y_cold"], "total", "mkt_total"),
    }
    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=1)
    print(json.dumps({k: v for k, v in results.items()
                      if k.startswith(("core_margin_A", "resid_margin_A"))},
                     indent=1))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
