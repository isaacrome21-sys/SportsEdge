"""NFL player props, simple engine step (one script, one test).

The simple method has two halves. Half 1, "copy the book", needs the book's
historical prop lines, and there is no free archive of those (none in the repo,
none in nflverse). So only half 2, "our own view", can be tested on history.

Own view: each player's stat is an exponentially weighted average of his prior
regular-season games (this season, plus last season's games at weight c).
P(over line) comes from the empirical ratio y / mu seen on the training seasons.

Test: settings (half-life h, carry-over c) are picked on 2018-2022 by mean
absolute error, frozen, then run once on 2024-2026 (2023 is a gap year that is
used only as the prior season for 2024). Reported: MAE vs a naive season-average,
and over-rate calibration at the Part 2 line proxy (floor(median prior) + 0.5).
No book lines exist for these seasons, so there is no ROI and no edge claim.

`price` mode applies the frozen view to a DK capture file (CSV with columns
player,market,line,over_odds,under_odds) and lists gaps vs the no-vig book
price. The gap threshold GAP is a declared constant, NOT tuned on history
(no lines to tune on); anything it produces is paper only.

usage:
  python simple/props_nfl.py test  DATA_DIR      # ps_YYYY.csv (<=2024), sp_YYYY.csv (>=2025)
  python simple/props_nfl.py price DATA_DIR SEASON CAPTURE.csv
"""
import csv, math, sys, os, json, bisect
from collections import defaultdict

MARKETS = {  # market: (stat column, opportunity column)
    "PASS_YDS": ("passing_yards", "attempts"),
    "RUSH_YDS": ("rushing_yards", "carries"),
    "REC_YDS": ("receiving_yards", "targets"),
    "RECEPTIONS": ("receptions", "targets"),
}
TRAIN, GAP_YEAR, TEST = range(2018, 2023), 2023, range(2024, 2027)
GRID_H, GRID_C = (2, 4, 8, 16), (0.0, 0.25, 0.5, 1.0)
MIN_PRIOR = 3          # prior same-season games with opportunity > 0
GAP = 0.06             # declared, untuned (price mode only)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load(data_dir, years):
    rows = []  # (season, week, pid, name, {market: (y, opp)})
    for yr in years:
        p = os.path.join(data_dir, ("ps_%d.csv" if yr <= 2024 else "sp_%d.csv") % yr)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p, newline="")):
            if r.get("season_type") != "REG":
                continue
            m = {k: (f(r.get(s)), f(r.get(o))) for k, (s, o) in MARKETS.items()}
            rows.append((yr, int(r["week"]), r["player_id"], r.get("player_display_name", ""), m))
    rows.sort(key=lambda t: (t[0], t[1]))
    return rows


def history(rows):
    """For every row, the player's prior (season, y) list per market, oldest first."""
    hist = defaultdict(lambda: defaultdict(list))
    out = []
    for season, week, pid, name, m in rows:
        prior = {k: list(hist[pid][k]) for k in MARKETS}
        out.append((season, week, pid, name, m, prior))
        for k, (y, opp) in m.items():
            if opp > 0:
                hist[pid][k].append((season, y))
    return out


def mu(prior, season, h, c):
    num = den = 0.0
    for j, (s, y) in enumerate(reversed(prior)):
        if s == season:
            w = 0.5 ** (j / h)
        elif s == season - 1:
            w = c * 0.5 ** (j / h)
        else:
            continue
        num += w * y
        den += w
    return num / den if den > 0 else None


def rows_for(hrows, years, k):
    for season, week, pid, name, m, prior in hrows:
        if season not in years:
            continue
        y, opp = m[k]
        cur = [v for s, v in prior[k] if s == season]
        if opp > 0 and len(cur) >= MIN_PRIOR:
            yield season, y, prior[k], cur


def pick(hrows, k):
    best = None
    for h in GRID_H:
        for c in GRID_C:
            err = [abs(y - mu(p, s, h, c)) for s, y, p, cur in rows_for(hrows, TRAIN, k)]
            mae = sum(err) / len(err)
            if best is None or mae < best[0]:
                best = (mae, h, c, len(err))
    return best


def ratios(hrows, k, h, c):
    r = sorted(y / max(mu(p, s, h, c), 1e-6) for s, y, p, cur in rows_for(hrows, TRAIN, k))
    return r


def p_over(line, m, rat):
    if m <= 0:
        return None
    t = line / m
    return 1 - bisect.bisect_right(rat, t) / len(rat)


def run_test(data_dir):
    hrows = history(load(data_dir, range(2017, 2027)))
    res = {}
    for k in MARKETS:
        mae_tr, h, c, n_tr = pick(hrows, k)
        rat = ratios(hrows, k, h, c)
        e_m, e_n, buckets = [], [], defaultdict(lambda: [0, 0, 0.0])
        for s, y, p, cur in rows_for(hrows, TEST, k):
            m = mu(p, s, h, c)
            e_m.append(abs(y - m))
            e_n.append(abs(y - sum(cur) / len(cur)))
            srt = sorted(cur)
            med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2
            line = math.floor(med) + 0.5
            po = p_over(line, m, rat)
            if po is None:
                continue
            b = min(int(po * 10), 9)
            buckets[b][0] += 1
            buckets[b][1] += y > line
            buckets[b][2] += po
        cal = {"%.1f-%.1f" % (b / 10, b / 10 + .1): {"n": v[0], "pred_over": round(v[2] / v[0], 3),
               "actual_over": round(v[1] / v[0], 3)} for b, v in sorted(buckets.items()) if v[0] >= 30}
        res[k] = {"frozen": {"half_life_games": h, "carry_last_season": c}, "train_n": n_tr,
                  "train_mae": round(mae_tr, 2), "test_n": len(e_m),
                  "test_mae_model": round(sum(e_m) / len(e_m), 2),
                  "test_mae_season_avg": round(sum(e_n) / len(e_n), 2), "calibration_at_proxy": cal}
    return res


def american_to_p(o):
    o = float(o)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def run_price(data_dir, season, cap):
    season = int(season)
    hrows = history(load(data_dir, range(2017, season + 1)))
    names = {}
    last = defaultdict(dict)
    for s, w, pid, name, m, prior in hrows:
        names[name.lower()] = pid
    hist = defaultdict(lambda: defaultdict(list))
    for s, w, pid, name, m, prior in hrows:
        for k, (y, opp) in m.items():
            if opp > 0:
                hist[pid][k].append((s, y))
    out = []
    for r in csv.DictReader(open(cap, newline="")):
        k, pid = r["market"], names.get(r["player"].strip().lower())
        if k not in MARKETS or pid is None:
            out.append({**r, "status": "NO_MATCH"}); continue
        _, h, c, _ = pick(hrows, k)
        pr = hist[pid][k]
        if sum(1 for s, _ in pr if s == season) < MIN_PRIOR:
            out.append({**r, "status": "TOO_FEW_GAMES"}); continue
        m = mu(pr, season, h, c)
        po = p_over(float(r["line"]), m, ratios(hrows, k, h, c))
        a, b = american_to_p(r["over_odds"]), american_to_p(r["under_odds"])
        book = a / (a + b)
        gap = po - book
        side = "OVER" if gap >= GAP else "UNDER" if gap <= -GAP else ""
        out.append({**r, "mu": round(m, 1), "p_over_model": round(po, 3), "p_over_book_novig": round(book, 3),
                    "gap": round(gap, 3), "paper_side": side, "status": "OK"})
    return out


if __name__ == "__main__":
    if sys.argv[1] == "test":
        print(json.dumps(run_test(sys.argv[2]), indent=1))
    else:
        print(json.dumps(run_price(*sys.argv[2:5]), indent=1))
