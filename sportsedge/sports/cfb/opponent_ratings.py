"""Opponent-adjusted CFB offense/defense ratings (t273; RESEARCH ONLY).

Ridge-regularized points model, solved in closed form (equivalent to the
fixed point of iterated SRS with a ridge pull toward a prior):

    pts_home = mu + H*(1-neutral)/2 + off[home] - def[away]
    pts_away = mu - H*(1-neutral)/2 + off[away] - def[home]

``def`` is points PREVENTED vs average (positive = better defense). The
penalty pulls each team's off/def toward ``rho * prior`` (prior-season
final ratings; 0 for teams with none) with weight ``lam``; mu and H are
unpenalized but H is pulled to ``hfa_prior`` with weight ``lam_hfa``.

Point-in-time: only games whose kickoff is STRICTLY BEFORE ``as_of`` are
used. Inputs are final scores only; no market price ever enters.
Output is SCREEN / NOT_VALIDATED.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

STATUS = {"status_label": "SCREEN", "validation": "NOT_VALIDATED",
          "family": "CFB_OPPONENT_ADJUSTED_RIDGE_V1"}


def _when(x):
    """Aware UTC datetime from a datetime or ISO string ('Z' or offset)."""
    if not isinstance(x, datetime):
        text = str(x).strip().replace("Z", "+00:00")
        if len(text) == 22 and text[16] == "+":  # 'YYYY-MM-DDTHH:MM+00:00'
            text = text[:16] + ":00" + text[16:]
        x = datetime.fromisoformat(text)
    if x.tzinfo is None:
        raise ValueError("RATINGS_TIMESTAMP_TIMEZONE_REQUIRED")
    return x.astimezone(timezone.utc)


def fit_ratings(games, *, as_of, lam=8.0, prior=None, rho=0.5,
                hfa_prior=3.0, lam_hfa=50.0, mu_prior=27.0):
    cut = _when(as_of)
    used = [x for x in games if _when(x["date"]) < cut]
    prior_teams = (prior or {}).get("teams") or {}
    teams = sorted({t for x in used for t in (x["home"], x["away"])} | set(prior_teams))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    p = 2 + 2 * n  # mu, H, off[n], def[n]
    rows, y = [], []
    for x in used:
        hf = 0.0 if x.get("neutral") else 0.5
        for own, opp, pts, sgn in ((x["home"], x["away"], x["hs"], 1), (x["away"], x["home"], x["as"], -1)):
            r = np.zeros(p)
            r[0] = 1.0
            r[1] = sgn * hf
            r[2 + idx[own]] = 1.0
            r[2 + n + idx[opp]] = -1.0
            rows.append(r)
            y.append(float(pts))
    target = np.zeros(p)
    target[0] = mu_prior
    target[1] = hfa_prior
    for t, v in prior_teams.items():
        target[2 + idx[t]] = rho * float(v.get("off", 0.0))
        target[2 + n + idx[t]] = rho * float(v.get("def", 0.0))
    pen = np.full(p, float(lam))
    pen[0] = 1e-6
    pen[1] = float(lam_hfa)
    X = np.array(rows) if rows else np.zeros((0, p))
    Y = np.array(y) if y else np.zeros(0)
    A = X.T @ X + np.diag(pen)
    b = X.T @ Y + pen * target
    sol = np.linalg.solve(A, b)
    out = {"mu": float(sol[0]), "hfa": float(sol[1]), "n_games": len(used),
           "as_of": cut.isoformat(),
           "teams": {t: {"off": float(sol[2 + i]), "def": float(sol[2 + n + i])}
                     for t, i in idx.items()},
           **STATUS}
    if not used:
        out["mu"], out["hfa"] = float(mu_prior), float(hfa_prior)
    return out


def team(r, t):
    return r["teams"].get(t, {"off": 0.0, "def": 0.0})


def predict(r, home, away, neutral=False):
    h, a = team(r, home), team(r, away)
    hf = 0.0 if neutral else r["hfa"] / 2
    return (r["mu"] + hf + h["off"] - a["def"], r["mu"] - hf + a["off"] - h["def"])


# ---- live (pre-kickoff) ratings from the keyless ESPN scoreboard ----------
SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/football/"
              "college-football/scoreboard?dates={season}&seasontype={st}"
              "&week={week}&groups=80&limit=400")
# 2024-only hyperparameter fit (scripts/cfb_calibration/backtest_opponent_ratings.py)
LIVE_LAM = 1.0
LIVE_RHO = 1.0


def _season_games(fetch, season):
    out = []
    for st, weeks in ((2, range(1, 17)), (3, range(1, 2))):
        for w in weeks:
            board = fetch(SCOREBOARD.format(season=season, st=st, week=w)) or {}
            for e in board.get("events") or []:
                try:
                    c = e["competitions"][0]
                    if not c["status"]["type"].get("completed"):
                        continue
                    t = {x["homeAway"]: x for x in c["competitors"]}
                    out.append({"date": e["date"], "home": str(t["home"]["team"]["id"]),
                                "away": str(t["away"]["team"]["id"]),
                                "hs": float(t["home"]["score"]), "as": float(t["away"]["score"]),
                                "neutral": bool(c.get("neutralSite"))})
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
    return out


def live_ratings(fetch, kickoff):
    """Ratings as of the START of the kickoff's UTC day: prior = previous
    season's final ratings; current-season games strictly before that."""
    k = _when(kickoff)
    season = k.year if k.month > 2 else k.year - 1
    prev = _season_games(fetch, season - 1)
    prior = fit_ratings(prev, as_of=datetime(season, 3, 1, tzinfo=timezone.utc),
                        lam=LIVE_LAM) if prev else None
    cut = datetime(k.year, k.month, k.day, tzinfo=timezone.utc)
    return fit_ratings(_season_games(fetch, season), as_of=cut, lam=LIVE_LAM,
                       prior=prior, rho=LIVE_RHO,
                       mu_prior=prior["mu"] if prior else 27.0)
