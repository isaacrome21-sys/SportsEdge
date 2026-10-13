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


def run_period_harness(games, quarter_games, *, min_team_games=10, n_paths=3000):
    """1H and Q1 total over-probabilities from the joint quarter simulation.

    Lines are NAIVE STAND-INS (train mean 1H / Q1 total), NOT market lines.
    Ratings and quarter calibration both use only games before the slate.
    """
    from .quarter_joint_sim import calibrate, simulate, markets
    qmap = {q.game_id: q for q in quarter_games}
    games = sorted((g for g in games if g.game_id in qmap), key=lambda g: (g.start, g.game_id))
    by_day = defaultdict(list)
    for g in games:
        by_day[g.start.date()].append(g)
    h1, q1, ml_cons = [], [], []
    for day in sorted(by_day):
        slate = by_day[day]
        cutoff = min(g.start for g in slate)
        train = [g for g in games if g.start < cutoff]
        if len(train) < 30:
            continue
        r = fit_asof(train, cutoff)
        cal = calibrate([qmap[g.game_id] for g in train], cutoff)
        tq = [qmap[g.game_id] for g in train]
        h1_line = sum(sum(q.home_lines[:2]) + sum(q.away_lines[:2]) for q in tq) / len(tq)
        q1_line = sum(q.home_lines[0] + q.away_lines[0] for q in tq) / len(tq)
        h1_rate = sum((sum(q.home_lines[:2]) + sum(q.away_lines[:2])) > h1_line for q in tq) / len(tq)
        q1_rate = sum((q.home_lines[0] + q.away_lines[0]) > q1_line for q in tq) / len(tq)
        for g in slate:
            if min(r.games_by_team.get(g.home, 0), r.games_by_team.get(g.away, 0)) < min_team_games:
                continue
            p = r.predict(g.home, g.away)
            H, A = simulate(cal, p["home_points"], p["away_points"], n=n_paths,
                            seed=int(g.game_id) % (2 ** 31) if g.game_id.isdigit() else 0)
            m = markets(H, A)
            q = qmap[g.game_id]
            y1 = sum(q.home_lines[:2]) + sum(q.away_lines[:2])
            yq = q.home_lines[0] + q.away_lines[0]
            h1.append({"model": float((m["h1_total"] > h1_line).mean()), "naive": h1_rate, "y": int(y1 > h1_line)})
            q1.append({"model": float((m["q1_total"] > q1_line).mean()), "naive": q1_rate, "y": int(yq > q1_line)})
            ml_cons.append(abs(m["home_ml"] - float((m["margin"] > 0).mean())))
    return {"H1_TOTAL_NAIVE_STANDIN_LINE": _score(h1), "Q1_TOTAL_NAIVE_STANDIN_LINE": _score(q1),
            "lines": "NAIVE_STANDIN_TRAIN_MEAN_NOT_MARKET",
            "max_ml_vs_margin_inconsistency": max(ml_cons) if ml_cons else None,
            "market_baseline": "MISSING_NO_PAIRED_TIMESTAMPED_ODDS",
            "rest_adj": 0.0, "research_only": True}
