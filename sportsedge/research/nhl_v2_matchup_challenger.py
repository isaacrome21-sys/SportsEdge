"""NHL v2 matchup challenger (RESEARCH ONLY, not wired to production).

Unit-vs-unit inputs, all point-in-time (built only from games on strictly
earlier calendar dates, plus the starting goalies, which are public before
puck drop):

* 5v5 offence vs 5v5 defence: rolling, shrunk xGF/60 and xGA/60.
* Special teams: own PP xG/min x opponent PK xGA/min x expected PP minutes
  (own penalties drawn vs opponent penalties taken).
* Goalie vs shooters: the opponent starter's goals saved above expected per xG
  faced (rolling, shrunk toward 0), carried across seasons.
* Schedule: rest days, back-to-back, travel km since last game.
* Home ice.
* Optional market anchor (opening line only; never the close).

Regulation goals per side ~ Poisson GLM (log link) with an optional
regulation-tie inflation; OT/SO resolved as a coin flip, as in v1.

Nothing here is imported by production code. No thresholds or promotion.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

SHOT_TYPES = ("Wrist", "Snap ", "Slap ", "Backh", "Tip-I", "Wrap-", "Defle")
PP_STATES = {"5v4", "5v3", "4v3", "6v4", "6v3"}

ARENA = {
    "ANA": (33.81, -117.88), "ARI": (33.53, -112.26), "BOS": (42.37, -71.06),
    "BUF": (42.88, -78.88), "CGY": (51.04, -114.05), "CAR": (35.80, -78.72),
    "CHI": (41.88, -87.67), "COL": (39.75, -105.01), "CBJ": (39.97, -83.01),
    "DAL": (32.79, -96.81), "DET": (42.34, -83.05), "EDM": (53.55, -113.50),
    "FLA": (26.16, -80.33), "LAK": (34.04, -118.27), "MIN": (44.94, -93.10),
    "MTL": (45.50, -73.57), "NSH": (36.16, -86.78), "NJD": (40.73, -74.17),
    "NYI": (40.72, -73.59), "NYR": (40.75, -73.99), "OTT": (45.30, -75.93),
    "PHI": (39.90, -75.17), "PIT": (40.44, -79.99), "SJS": (37.33, -121.90),
    "SEA": (47.62, -122.35), "STL": (38.63, -90.20), "TBL": (27.94, -82.45),
    "TOR": (43.64, -79.38), "VAN": (49.28, -123.11), "VGK": (36.10, -115.18),
    "WSH": (38.90, -77.02), "WPG": (49.89, -97.14),
}


def km(a, b):
    (la1, lo1), (la2, lo2) = ARENA.get(a, (0, 0)), ARENA.get(b, (0, 0))
    p1, p2 = math.radians(la1), math.radians(la2)
    dl = math.radians(lo2 - lo1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 6371.0 * math.acos(max(-1.0, min(1.0, c)))


# ---------------------------------------------------------------- shot xG model
def shot_row(s, prev_t):
    """s = [side, outcome, dist, angle, strength, type5, empty_net, goalie, period, t]."""
    d = s[2] if s[2] is not None else 35.0
    a = abs(s[3]) if s[3] is not None else 30.0
    st = s[4] or "5v5"
    pp = 1.0 if st in PP_STATES else 0.0
    sh = 1.0 if st in {"4v5", "3v5", "3v4"} else 0.0
    reb = 1.0 if (prev_t is not None and s[9] is not None and 0 <= s[9] - prev_t <= 3) else 0.0
    ty = [1.0 if s[5] == t else 0.0 for t in SHOT_TYPES[1:]]
    return [1.0, math.log1p(d), d / 50.0, a / 45.0, (a / 45.0) ** 2, pp, sh, reb] + ty


def game_shot_matrix(g):
    X, y, keep = [], [], []
    prev = {0: None, 1: None}
    for i, s in enumerate(g["shots"]):
        if s[6]:  # empty net excluded from xG / GSAx
            prev[s[0]] = s[9]
            continue
        X.append(shot_row(s, prev[s[0]]))
        y.append(1.0 if s[1] == 1 else 0.0)
        keep.append(i)
        prev[s[0]] = s[9]
    return X, y, keep


def fit_logit(X, y, l2=1e-3, iters=40):
    X, y = np.asarray(X), np.asarray(y)
    w = np.zeros(X.shape[1])
    w[0] = math.log(y.mean() / (1 - y.mean()))
    for _ in range(iters):
        mu = 1 / (1 + np.exp(-(X @ w)))
        H = (X * (mu * (1 - mu))[:, None]).T @ X + l2 * len(y) * np.eye(len(w))
        step = np.linalg.solve(H, X.T @ (y - mu) - l2 * len(y) * w)
        w += step
        if np.max(np.abs(step)) < 1e-9:
            break
    return w


def fit_xg(games):
    X, y = [], []
    for g in games:
        a, b, _ = game_shot_matrix(g)
        X += a
        y += b
    return fit_logit(X, y)


def annotate_xg(g, w):
    X, _, keep = game_shot_matrix(g)
    xg = [0.0] * len(g["shots"])
    if X:
        p = 1 / (1 + np.exp(-(np.asarray(X) @ w)))
        for i, v in zip(keep, p):
            xg[i] = float(v)
    g["xg"] = xg


# ---------------------------------------------------------------- state / features
class State:
    """Exponentially-decayed sums. Updated only after a calendar day is featurized."""

    def __init__(self, decay=0.97, goalie_decay=0.98, k_team_min=300.0, k_pp_min=60.0,
                 k_goalie_xg=60.0):
        self.decay, self.gdecay = decay, goalie_decay
        self.k_team, self.k_pp, self.k_g = k_team_min, k_pp_min, k_goalie_xg
        self.t = defaultdict(lambda: defaultdict(float))
        self.goalie = defaultdict(lambda: [0.0, 0.0])  # decayed (xg_faced, goals_allowed)
        self.last = {}  # team -> (date_ordinal, venue_team)
        self.lg = defaultdict(float)

    def new_season(self):
        for d in self.t.values():
            for k in d:
                d[k] *= 0.5  # partial carry-over of team form across seasons

    def team_feats(self):
        lg = self.lg
        ev = lg["ev_xg"] / max(lg["ev_min"], 1.0)
        pp = lg["pp_xg"] / max(lg["pp_min"], 1.0)
        ppm = lg["pp_min"] / max(lg["gp"], 1.0)
        gpm = lg["goals"] / max(lg["gp"], 1.0)
        return ev, pp, ppm, gpm

    def features(self, g, side, day):
        """Feature dict for `side` (0 home, 1 away) attacking."""
        ev_l, pp_l, ppm_l, g_l = self.team_feats()
        me, op = (g["home"], g["away"]) if side == 0 else (g["away"], g["home"])
        T, O = self.t[me], self.t[op]
        kt, kp = self.k_team, self.k_pp
        evf = (T["ev_xgf"] + kt * ev_l) / (T["ev_min"] + kt)
        eva = (O["ev_xga"] + kt * ev_l) / (O["ev_min"] + kt)
        ppf = (T["pp_xgf"] + kp * pp_l) / (T["pp_min"] + kp)
        pka = (O["pk_xga"] + kp * pp_l) / (O["pk_min"] + kp)
        drawn = (T["drawn_min"] + 10 * ppm_l) / (T["gp"] + 10)
        taken = (O["taken_min"] + 10 * ppm_l) / (O["gp"] + 10)
        gf = (T["gf"] + 10 * g_l) / (T["gp"] + 10)
        ga = (O["ga"] + 10 * g_l) / (O["gp"] + 10)
        og = g["ag"] if side == 0 else g["hg"]
        gx, gg = self.goalie[og]
        q = (gx - gg) / (gx + self.k_g)  # saves above expected per xG (shrunk to 0)
        rest = {}
        for tag, team in (("me", me), ("op", op)):
            prev = self.last.get(team)
            if prev is None:
                rest[tag] = (3.0, 0.0, 0.0)
            else:
                dd = day - prev[0]
                rest[tag] = (min(dd, 4), 1.0 if dd == 1 else 0.0, km(prev[1], g["home"]) / 1000.0)
        ev_match = evf * eva / ev_l * 50.0  # ~5v5 minutes per game
        pp_match = ppf * pka / pp_l * math.sqrt(drawn * taken)
        return {
            "log_ev": math.log(ev_match), "log_pp": math.log(max(pp_match, 1e-3)),
            "log_ev_lg": math.log(ev_l * 50.0), "log_pp_lg": math.log(pp_l * ppm_l),
            "goalie": math.log(max(1.0 - q, 0.5)),
            "log_gfga": math.log(gf * ga / g_l),
            "b2b_me": rest["me"][1], "b2b_op": rest["op"][1],
            "rest_diff": rest["me"][0] - rest["op"][0],
            "trav_me": rest["me"][2], "trav_op": rest["op"][2],
            "home": 1.0 if side == 0 else 0.0,
            "_opp_goalie": og, "_goalie_xg_n": gx,
        }

    def update(self, g, day):
        dec = self.decay
        for team in (g["home"], g["away"]):
            for k in self.t[team]:
                self.t[team][k] *= dec
        toi = g.get("toi") or {}
        ev_min = toi.get("5v5", 0) / 60.0
        pp_h = sum(v for k, v in toi.items() if k in PP_STATES) / 60.0  # home on PP
        pp_a = sum(v for k, v in toi.items() if "%sv%s" % tuple(reversed(k.split("v"))) in PP_STATES) / 60.0
        xs = defaultdict(float)
        for s, x in zip(g["shots"], g["xg"]):
            side = s[0]
            st = s[4] or ""
            if st == "5v5":
                xs[("ev", side)] += x
            elif st in PP_STATES:
                xs[("pp", side)] += x
            if not s[6] and s[7]:
                gl = self.goalie[s[7]]
                gl[0] += x
                gl[1] += 1.0 if s[1] == 1 else 0.0
        H, A = self.t[g["home"]], self.t[g["away"]]
        for T, me, op, ppm, pkm, gf, ga in ((H, 0, 1, pp_h, pp_a, g["hreg"], g["areg"]),
                                            (A, 1, 0, pp_a, pp_h, g["areg"], g["hreg"])):
            T["ev_xgf"] += xs[("ev", me)]; T["ev_xga"] += xs[("ev", op)]; T["ev_min"] += ev_min
            T["pp_xgf"] += xs[("pp", me)]; T["pp_min"] += ppm
            T["pk_xga"] += xs[("pp", op)]; T["pk_min"] += pkm
            T["drawn_min"] += ppm; T["taken_min"] += pkm
            T["gf"] += gf; T["ga"] += ga; T["gp"] += 1.0
        for gid in (g["hg"], g["ag"]):
            if gid:
                v = self.goalie[gid]
                v[0] *= self.gdecay; v[1] *= self.gdecay  # per appearance
        lg = self.lg
        for k in lg:
            lg[k] *= 0.995
        lg["ev_xg"] += xs[("ev", 0)] + xs[("ev", 1)]; lg["ev_min"] += 2 * ev_min
        lg["pp_xg"] += xs[("pp", 0)] + xs[("pp", 1)]; lg["pp_min"] += pp_h + pp_a
        lg["goals"] += g["hreg"] + g["areg"]; lg["gp"] += 2
        self.last[g["home"]] = (day, g["home"])
        self.last[g["away"]] = (day, g["home"])


# ---------------------------------------------------------------- GLM + distribution
FEATURE_SETS = {
    "core": ["log_ev", "log_pp", "home", "b2b_me", "b2b_op", "rest_diff", "trav_me"],
    "goalie": ["log_ev", "log_pp", "goalie", "home", "b2b_me", "b2b_op", "rest_diff", "trav_me"],
    "goalie_gf": ["log_ev", "log_pp", "goalie", "log_gfga", "home", "b2b_me", "b2b_op", "rest_diff", "trav_me"],
    "goalie_mkt": ["log_ev", "log_pp", "goalie", "home", "b2b_me", "b2b_op", "rest_diff", "trav_me",
                   "mkt_logit", "mkt_total"],
}


def fit_poisson(X, y, l2=1e-4, iters=60):
    X, y = np.asarray(X), np.asarray(y, float)
    w = np.zeros(X.shape[1]); w[0] = math.log(max(y.mean(), 1e-3))
    for _ in range(iters):
        mu = np.exp(np.clip(X @ w, -8, 4))
        H = (X * mu[:, None]).T @ X + l2 * len(y) * np.eye(len(w))
        step = np.linalg.solve(H, X.T @ (y - mu) - l2 * len(y) * w)
        w += step
        if np.max(np.abs(step)) < 1e-10:
            break
    return w


def score_dist(lh, la, tie_infl=0.0, kmax=15):
    ph = [math.exp(-lh)]; pa = [math.exp(-la)]
    for k in range(1, kmax + 1):
        ph.append(ph[-1] * lh / k); pa.append(pa[-1] * la / k)
    base = np.outer(ph, pa)
    reg = base
    if tie_infl:
        diag = float(np.trace(base))
        off = base.copy(); np.fill_diagonal(off, 0.0)
        reg = off * (1.0 - diag * (1.0 + tie_infl)) / max(off.sum(), 1e-9)
        np.fill_diagonal(reg, np.diag(base) * (1.0 + tie_infl))
    d = defaultdict(float)
    n = reg.shape[0]
    for i in range(n):
        for j in range(n):
            p = float(reg[i, j])
            if i == j:
                d[(i + 1, j)] += 0.5 * p; d[(i, j + 1)] += 0.5 * p
            else:
                d[(i, j)] += p
    z = sum(d.values())
    return {k: v / z for k, v in d.items()}


def fit_tie_inflation(lams, ties):
    """Moment match: observed regulation-tie rate vs Poisson-implied."""
    imp = []
    for lh, la in lams:
        ph = np.exp(-lh) * lh ** np.arange(16) / np.array([math.factorial(k) for k in range(16)])
        pa = np.exp(-la) * la ** np.arange(16) / np.array([math.factorial(k) for k in range(16)])
        imp.append(float(np.dot(ph, pa)))
    return float(np.mean(ties) / np.mean(imp) - 1.0)
