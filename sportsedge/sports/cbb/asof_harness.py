"""CBB walk-forward per docs/CBB_ASOF_RATINGS_PREREG_20261013.md.

Lines are NAIVE_STANDIN point estimates, not market lines. Market baseline MISSING.
Illinois games (by ESPN id) are excluded from evaluation and output.
"""
from __future__ import annotations

from collections import defaultdict
from math import log
from zoneinfo import ZoneInfo

from .asof_ratings import fit_asof, illinois_block, trainable

CT = ZoneInfo("America/Chicago")
EPS = 1e-6
MIN_TEAM_GAMES = 5
MIN_TRAIN = 200


def _ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * log(p) + (1 - y) * log(1 - p))


def run_harness(games) -> dict:
    games = sorted({g.game_id: g for g in games}.values(), key=lambda g: (g.start, g.game_id))
    by_day = defaultdict(list)
    for g in games:
        by_day[g.start.astimezone(CT).date()].append(g)
    acc = {k: [0, 0.0, 0.0, 0.0, 0.0] for k in ("moneyline", "spread", "total")}
    excluded_il = 0
    for day in sorted(by_day):
        slate = by_day[day]
        cutoff = min(g.start for g in slate)
        train = [g for g in games if trainable(g, cutoff)]
        if len(train) < MIN_TRAIN:
            continue
        r = fit_asof(train, cutoff)
        pf, pa, cnt = defaultdict(float), defaultdict(float), defaultdict(int)
        for g in train:
            for t, f, a in ((g.home_id, g.home_points, g.away_points), (g.away_id, g.away_points, g.home_points)):
                pf[t] += f
                pa[t] += a
                cnt[t] += 1
        nn = [g for g in train if not g.neutral]
        home_rate = sum(g.home_points > g.away_points for g in nn) / len(nn)
        for g in slate:
            if illinois_block(g.home_id, g.away_id):
                excluded_il += 1
                continue
            if not g.completed or min(cnt.get(g.home_id, 0), cnt.get(g.away_id, 0)) < MIN_TEAM_GAMES:
                continue
            p = r.predict(g.home_id, g.away_id, neutral=g.neutral)
            avg_m = lambda t: (pf[t] - pa[t]) / cnt[t]
            spread_line = (avg_m(g.home_id) - avg_m(g.away_id)) / 2 + (0 if g.neutral else r.hca)
            total_line = ((pf[g.home_id] + pa[g.home_id]) / cnt[g.home_id] +
                          (pf[g.away_id] + pa[g.away_id]) / cnt[g.away_id]) / 2
            margin, total = g.home_points - g.away_points, g.home_points + g.away_points
            items = [("moneyline", p["p_home_win"], 0.5 if g.neutral else home_rate, int(margin > 0))]
            if margin != spread_line:
                items.append(("spread", r.p_home_cover(p, spread_line), 0.5, int(margin > spread_line)))
            if total != total_line:
                items.append(("total", r.p_over(p, total_line), 0.5, int(total > total_line)))
            for k, pm, pn, y in items:
                a = acc[k]
                a[0] += 1
                a[1] += (pm - y) ** 2
                a[2] += (pn - y) ** 2
                a[3] += _ll(pm, y)
                a[4] += _ll(pn, y)
    out = {k: {"n": v[0], "brier_model": round(v[1] / max(v[0], 1), 5), "brier_naive": round(v[2] / max(v[0], 1), 5),
               "ll_model": round(v[3] / max(v[0], 1), 5), "ll_naive": round(v[4] / max(v[0], 1), 5)}
           for k, v in acc.items()}
    passed = all(out[k]["n"] and out[k]["brier_model"] < out[k]["brier_naive"] for k in out) and \
        out["moneyline"]["ll_model"] < out["moneyline"]["ll_naive"]
    return {"markets": out, "decision": "PASS_RESEARCH" if passed else "FAIL", "lines": "NAIVE_STANDIN",
            "market_baseline": "MISSING", "illinois_games_excluded": excluded_il}
