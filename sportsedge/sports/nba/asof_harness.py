"""Chronological walk-forward game-market harness for as-of NBA ratings.

Research only. For each slate date, ratings are fit on games strictly before
the earliest start that day, then that day's games are scored. Spread/total
binary events use NAIVE_PROXY lines (train mean margin / train mean total),
because no paired, timestamped market lines exist in the repo: the MARKET
baseline leg is MISSING and no promotion can follow from this report.
"""
from __future__ import annotations

from collections import defaultdict
from math import erf, log, sqrt

from .asof_team_ratings import fit_asof

EPS = 1e-6


def _phi(z):
    return 0.5 * (1 + erf(z / sqrt(2)))


def _clip(p):
    return min(1 - EPS, max(EPS, p))


def _score(rows):
    if not rows:
        return {"n": 0}
    out = {"n": len(rows)}
    for k in ("model", "naive"):
        out[k + "_brier"] = round(sum((r[k] - r["y"]) ** 2 for r in rows) / len(rows), 5)
        out[k + "_logloss"] = round(-sum(r["y"] * log(_clip(r[k])) + (1 - r["y"]) * log(1 - _clip(r[k]))
                                         for r in rows) / len(rows), 5)
    return out


def run_harness(games, *, min_team_games=10, sd_prior=12.0, total_sd_prior=18.0):
    games = sorted(games, key=lambda g: (g.start, g.game_id))
    by_day = defaultdict(list)
    for g in games:
        by_day[g.start.date()].append(g)
    ml, sp, tot = [], [], []
    past = []  # (margin_err, total_err) from earlier OUT-OF-SAMPLE predictions only
    for day in sorted(by_day):
        slate = by_day[day]
        cutoff = min(g.start for g in slate)
        train = [g for g in games if g.start < cutoff]
        if len(train) < 30:
            continue
        r = fit_asof(train, cutoff)
        n = len(train)
        home_win_rate = sum(g.home_points > g.away_points for g in train) / n
        m_line = sum(g.home_points - g.away_points for g in train) / n
        t_line = sum(g.home_points + g.away_points for g in train) / n
        sp_rate = sum((g.home_points - g.away_points) > m_line for g in train) / n
        to_rate = sum((g.home_points + g.away_points) > t_line for g in train) / n
        msd = (sqrt(sum(e * e for e, _ in past) / len(past)) if len(past) >= 100 else sd_prior)
        tsd = (sqrt(sum(e * e for _, e in past) / len(past)) if len(past) >= 100 else total_sd_prior)
        preds = []
        for g in slate:
            if min(r.games_by_team.get(g.home, 0), r.games_by_team.get(g.away, 0)) < min_team_games:
                continue
            p = r.predict(g.home, g.away)
            mar = g.home_points - g.away_points
            tt = g.home_points + g.away_points
            ml.append({"model": _phi(p["margin"] / msd), "naive": home_win_rate, "y": int(mar > 0)})
            sp.append({"model": _phi((p["margin"] - m_line) / msd), "naive": sp_rate, "y": int(mar > m_line)})
            tot.append({"model": _phi((p["total"] - t_line) / tsd), "naive": to_rate, "y": int(tt > t_line)})
            preds.append((mar - p["margin"], tt - p["total"]))
        past.extend(preds)  # appended only after the whole slate is scored
    return {"MONEYLINE": _score(ml), "SPREAD_NAIVE_PROXY_LINE": _score(sp),
            "TOTAL_NAIVE_PROXY_LINE": _score(tot),
            "market_baseline": "MISSING_NO_PAIRED_TIMESTAMPED_ODDS",
            "rest_adj": 0.0, "research_only": True}
