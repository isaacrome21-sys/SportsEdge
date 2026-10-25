"""NHL v2 matchup challenger backtest (#2447). HISTORICAL ONLY.

Does not touch the frozen Oct 8 - Nov 30 2026 window, production models,
thresholds or promotion. Challenger module: sportsedge/research/nhl_v2_matchup_challenger.py

Protocol (fixed before any result was seen):
  * Dev: seasons 2012-2019 (SBR season label = start year), walk-forward: each
    season scored by a GLM fit only on earlier seasons (2011 = warm-up).
  * Validation: 2020 (2020-21), fit on <=2019. Used ONLY to choose one attempt.
  * Final test: 2021 (2021-22), fit on <=2020, evaluated ONCE with the chosen attempt
    (only the chosen attempt is ever run with test_ok=True).
Max 8 attempts, all logged.

Inputs:
  odds: flancast90/sportsbookreview-scraper@1a820e50 data/nhl_archive_10Y.json
  pbp:  sportsdataverse/fastRhockey-data nhl/json/<gameid>.json, reduced by extract_pbp.py
        to games_<year>.jsonl (shots with distance/angle/type/strength/goalie, TOI by
        manpower state, starting goalies).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
from metrics import EV_THRESHOLD, american_to_decimal, git_blob_sha1, implied, market_report, no_vig  # noqa: E402
from sportsedge.research import nhl_v2_matchup_challenger as M  # noqa: E402

SOURCE_BLOB = "9dd97a3064b8001039e3cc06a4b4657f338a4045"
DEV = list(range(2012, 2020))
VAL, TEST = 2020, 2021
TOTALS_OVERROUND = 0.045
NICK = {"Ducks": "ANA", "Coyotes": "ARI", "Phoenix": "ARI", "Arizonas": "ARI", "Bruins": "BOS",
        "Sabres": "BUF", "Flames": "CGY", "Hurricanes": "CAR", "Blackhawks": "CHI", "Avalanche": "COL",
        "Blue Jackets": "CBJ", "Stars": "DAL", "Red Wings": "DET", "Oilers": "EDM", "Panthers": "FLA",
        "Kings": "LAK", "Wild": "MIN", "Canadiens": "MTL", "Predators": "NSH", "Devils": "NJD",
        "Islanders": "NYI", "NY Islanders": "NYI", "Rangers": "NYR", "Senators": "OTT", "Flyers": "PHI",
        "Penguins": "PIT", "Sharks": "SJS", "SeattleKraken": "SEA", "Kraken": "SEA", "St.Louis": "STL",
        "Lightning": "TBL", "Tampa Bay": "TBL", "Tampa": "TBL", "Maple Leafs": "TOR", "Canucks": "VAN",
        "Golden Knights": "VGK", "Capitals": "WSH", "Jets": "WPG", "WinnipegJets": "WPG"}
TRI_FIX = {"PHX": "ARI", "L.A": "LAK", "N.J": "NJD", "S.J": "SJS", "T.B": "TBL", "ATL": "WPG"}

ATTEMPTS = [
    # id, feature set, tie inflation, state kwargs, note
    (1, "core", False, {}, "5v5 xG matchup + PP/PK matchup + rest/b2b/travel + home; no goalie"),
    (2, "goalie", False, {}, "attempt 1 + opposing starter GSAx/xG (shrunk, k=60 xG)"),
    (3, "goalie_gf", False, {}, "attempt 2 + shrunk GF x opp GA (finishing/results)"),
    (4, "goalie", True, {}, "attempt 2 + regulation-tie inflation (fit on train)"),
    (5, "goalie_mkt", True, {}, "attempt 4 + OPENING-line anchor (no-vig ML logit, open total)"),
    (6, "goalie_mkt", True, {"decay": 0.985, "k_goalie_xg": 120.0},
     "attempt 5 with slower team decay and stronger goalie shrinkage"),
]


def load_odds(path, fix_2020_dates=False):
    """fix_2020_dates: SBR labels 2020-21 games played Jan-Mar 2021 with year 2020.
    Found AFTER the locked test was scored; default False reproduces the locked run."""
    raw = path.read_bytes()
    if git_blob_sha1(raw) != SOURCE_BLOB:
        raise SystemExit("SOURCE_BLOB_MISMATCH")
    out = {}
    for x in json.loads(raw):
        h, a = NICK.get(str(x["home_team"])), NICK.get(str(x["away_team"]))
        if not h or not a:
            continue
        d = str(int(x["date"]))
        if fix_2020_dates and x["season"] == 2020 and d[:6] in ("202001", "202002", "202003"):
            d = "2021" + d[4:]
        out[(f"{d[:4]}-{d[4:6]}-{d[6:]}", h)] = x
    return out


def load_games(pbp_dir):
    games = []
    for f in sorted(pbp_dir.glob("games_*.jsonl")):
        for line in f.open():
            g = json.loads(line)
            if not g.get("shots") or not g.get("hg") or not g.get("ag"):
                continue
            g["home"] = TRI_FIX.get(g["home"], g["home"]); g["away"] = TRI_FIX.get(g["away"], g["away"])
            g["season"] = int(str(g["gid"])[:4])
            reg = [s for s in g["shots"] if s[1] == 1 and (s[8] or 0) <= 3]
            g["hreg"] = sum(1 for s in reg if s[0] == 0); g["areg"] = sum(1 for s in reg if s[0] == 1)
            g["day"] = dt.date.fromisoformat(g["date"]).toordinal()
            games.append(g)
    games.sort(key=lambda g: (g["day"], g["gid"]))
    return games


def build(games, odds, state_kw):
    """Stream by calendar day; featurize a day's games before any enters state."""
    # xG weights for season s: fit on shots from seasons < s (2011: own season, warm-up only)
    seasons = sorted({g["season"] for g in games})
    xgw = {}
    for s in seasons:
        tr = [g for g in games if g["season"] < s] or [g for g in games if g["season"] == s]
        xgw[s] = M.fit_xg(tr[-6000:])
    for g in games:
        M.annotate_xg(g, xgw[g["season"]])
    st = M.State(**state_kw); st.n_games = 0
    rows, leaks, cur = [], 0, None
    i = 0
    while i < len(games):
        j = i
        while j < len(games) and games[j]["day"] == games[i]["day"]:
            j += 1
        if cur is not None and games[i]["season"] != cur:
            st.new_season()
        cur = games[i]["season"]
        for g in games[i:j]:
            x = odds.get((g["date"], g["home"]))
            if x is None or NICK.get(str(x["away_team"])) != g["away"] or not str(x.get("home_final", "")).isdigit() or not str(x.get("away_final", "")).isdigit():
                continue
            if st.n_games < 200:
                continue
            fh, fa = st.features(g, 0, g["day"]), st.features(g, 1, g["day"])
            ho, ao, ot = x.get("home_open_ml"), x.get("away_open_ml"), x.get("open_over_under")
            if ho and ao and abs(ho) >= 100 and abs(ao) >= 100 and ot and 3.5 <= ot <= 8.5:
                p = no_vig(ho, ao)[0]
                lo = math.log(p / (1 - p))
                fh["mkt_logit"], fa["mkt_logit"] = lo, -lo
                fh["mkt_total"] = fa["mkt_total"] = math.log(ot / 5.5)
            else:
                fh["mkt_logit"] = fa["mkt_logit"] = 0.0
                fh["mkt_total"] = fa["mkt_total"] = 0.0
            rows.append({"g": g, "x": x, "fh": fh, "fa": fa, "max_input_day": st_max(st)})
        for g in games[i:j]:
            st.update(g, g["day"]); st.n_games = getattr(st, "n_games", 0) + 1
            st._maxday = max(getattr(st, "_maxday", 0), g["day"])
        i = j
    for r in rows:
        if r["max_input_day"] >= r["g"]["day"]:
            leaks += 1
    return rows, leaks


def st_max(st):
    return getattr(st, "_maxday", 0)


def design(f, cols):
    return [1.0] + [f[c] for c in cols]


def fit(rows, cols, tie):
    X, y, lams, ties = [], [], [], []
    for r in rows:
        X += [design(r["fh"], cols), design(r["fa"], cols)]
        y += [r["g"]["hreg"], r["g"]["areg"]]
    w = M.fit_poisson(X, y)
    infl = 0.0
    if tie:
        for r in rows:
            lams.append((math.exp(np.dot(w, design(r["fh"], cols))), math.exp(np.dot(w, design(r["fa"], cols)))))
            ties.append(1.0 if r["g"]["hreg"] == r["g"]["areg"] else 0.0)
        infl = M.fit_tie_inflation(lams, ties)
    return w, infl


def totals_two_sided(uo):
    pu = implied(uo)
    po_vig = (1 + TOTALS_OVERROUND) - pu
    if not 0.05 < po_vig < 0.95:
        return None
    return {"p_under_nv": pu / (1 + TOTALS_OVERROUND), "over_dec": 1 / po_vig, "under_dec": american_to_decimal(uo)}


def score(rows, w, infl, cols):
    out = defaultdict(list)
    for r in rows:
        g, x = r["g"], r["x"]
        lh = math.exp(min(3.0, float(np.dot(w, design(r["fh"], cols)))))
        la = math.exp(min(3.0, float(np.dot(w, design(r["fa"], cols)))))
        dist = M.score_dist(lh, la, infl)
        hf, af = int(x["home_final"]), int(x["away_final"])  # outcomes from the odds archive (as v1)
        hw = sum(p for (h, a), p in dist.items() if h > a)
        hc, ac, ho, ao = x.get("home_close_ml"), x.get("away_close_ml"), x.get("home_open_ml"), x.get("away_open_ml")
        y = int(hf > af)
        if hc and ac and abs(hc) >= 100 and abs(ac) >= 100:
            pc = no_vig(hc, ac)[0]
            e = {"p_model": hw, "p_close": pc, "y": y, "bet_ev": None}
            if ho and ao and abs(ho) >= 100 and abs(ao) >= 100:
                po = no_vig(ho, ao)[0]
                eh, ea = hw * american_to_decimal(ho) - 1, (1 - hw) * american_to_decimal(ao) - 1
                if max(eh, ea) >= EV_THRESHOLD:
                    hs = eh >= ea
                    e.update(bet_ev=max(eh, ea), bet_dec=american_to_decimal(ho if hs else ao),
                             bet_won=y if hs else 1 - y, clv=(pc - po) if hs else (po - pc))
            out["moneyline"].append(e)
        L, uo, tot = x.get("close_over_under"), x.get("close_over_under_odds"), hf + af
        if L and uo and 3.5 <= L <= 8.5 and tot != L:
            tw = totals_two_sided(uo)
            if tw:
                o = sum(p for (h, a), p in dist.items() if h + a > L); u = sum(p for (h, a), p in dist.items() if h + a < L)
                e = {"p_model": o / (o + u), "p_close": 1 - tw["p_under_nv"], "y": int(tot > L), "bet_ev": None}
                OL, ouo = x.get("open_over_under"), x.get("open_over_under_odds")
                if OL and ouo and 3.5 <= OL <= 8.5 and (two := totals_two_sided(ouo)):
                    o2 = sum(p for (h, a), p in dist.items() if h + a > OL); u2 = sum(p for (h, a), p in dist.items() if h + a < OL)
                    evo, evu = o2 * two["over_dec"] + (1 - o2 - u2) - 1, u2 * two["under_dec"] + (1 - o2 - u2) - 1
                    if max(evo, evu) >= EV_THRESHOLD:
                        ov = evo >= evu
                        clv = None
                        if OL == L:
                            pc_, po_ = 1 - tw["p_under_nv"], 1 - two["p_under_nv"]
                            clv = (pc_ - po_) if ov else (po_ - pc_)
                        e.update(bet_ev=max(evo, evu), bet_dec=two["over_dec"] if ov else two["under_dec"],
                                 bet_won=None if tot == OL else int((tot > OL) == ov), clv=clv)
                out["totals"].append(e)
        sp, hso, aso = x.get("home_close_spread"), x.get("home_close_spread_odds"), x.get("away_close_spread_odds")
        if sp in (-1.5, 1.5) and hso and aso and abs(hso) >= 100 and abs(aso) >= 100:
            pc = no_vig(hso, aso)[0]
            c = sum(p for (h, a), p in dist.items() if h - a + sp > 0); n = 1 - c
            yc = int(hf - af + sp > 0)
            e = {"p_model": c, "p_close": pc, "y": yc, "bet_ev": None}
            eh, ea = c * american_to_decimal(hso) - 1, n * american_to_decimal(aso) - 1
            if max(eh, ea) >= EV_THRESHOLD:
                hs = eh >= ea
                e.update(bet_ev=max(eh, ea), bet_dec=american_to_decimal(hso if hs else aso),
                         bet_won=yc if hs else 1 - yc, clv=None)
            out["puck_line"].append(e)
    return out


UNITS = {"moneyline": "no-vig prob close minus open (bet at open)",
         "totals": "no-vig prob same line close minus open (bet at open)",
         "puck_line": "n/a (close only; bets at close)"}


def run_attempt(att, games, odds, test_ok):
    aid, fs, tie, kw, note = att
    cols = M.FEATURE_SETS[fs]
    rows, leaks = build(games, odds, kw)
    if leaks:
        raise SystemExit(f"LEAKAGE_CHECK_FAILED attempt {aid}: {leaks}")
    by = defaultdict(list)
    for r in rows:
        by[r["g"]["season"]].append(r)
    res = {"id": aid, "features": cols, "tie_inflation": tie, "state": kw, "note": note,
           "n_rows": len(rows), "leakage_violations": leaks}
    dev = defaultdict(list)
    for s in DEV:
        tr = [r for t in by if t < s for r in by[t]]
        if len(tr) < 800 or s not in by:
            continue
        w, infl = fit(tr, cols, tie)
        for m, v in score(by[s], w, infl, cols).items():
            dev[m] += v
    res["dev_walk_forward"] = {m: market_report(v, clv_unit=UNITS[m]) for m, v in dev.items()}
    tr = [r for t in by if t < VAL for r in by[t]]
    w, infl = fit(tr, cols, tie)
    res["validation_2020"] = {m: market_report(v, clv_unit=UNITS[m]) for m, v in score(by[VAL], w, infl, cols).items()}
    res["val_coefs"] = dict(zip(["intercept"] + cols, [round(float(c), 4) for c in w])); res["val_tie_infl"] = round(infl, 4)
    if test_ok:
        tr = [r for t in by if t < TEST for r in by[t]]
        w, infl = fit(tr, cols, tie)
        res["TEST_2021_LOCKED"] = {m: market_report(v, clv_unit=UNITS[m]) for m, v in score(by[TEST], w, infl, cols).items()}
        res["test_coefs"] = dict(zip(["intercept"] + cols, [round(float(c), 4) for c in w])); res["test_tie_infl"] = round(infl, 4)
        res["n_test_games"] = len(by[TEST])
    return res


def val_score(res):
    """Selection rule (declared up front): mean over markets of model-minus-close log-loss on validation."""
    v = res["validation_2020"]
    return float(np.mean([v[m]["logloss_model"] - v[m]["logloss_close_novig"] for m in ("moneyline", "totals", "puck_line")]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--odds", type=Path, required=True)
    ap.add_argument("--pbp", type=Path, required=True)
    ap.add_argument("--fix-2020-dates", action="store_true", help="post-hoc diagnostic; see README")
    ap.add_argument("--output", type=Path, default=HERE / "results.json")
    a = ap.parse_args(argv)
    odds, games = load_odds(a.odds, a.fix_2020_dates), load_games(a.pbp)
    log = []
    for att in ATTEMPTS:
        r = run_attempt(att, games, odds, test_ok=False)
        r["val_selection_score"] = val_score(r)
        log.append(r)
        print("attempt", r["id"], "val", round(r["val_selection_score"], 5),
              {m: (round(v["brier_model"] - v["brier_close_novig"], 5)) for m, v in r["validation_2020"].items()}, flush=True)
    chosen = min(log, key=lambda r: r["val_selection_score"])
    final = run_attempt(next(t for t in ATTEMPTS if t[0] == chosen["id"]), games, odds, test_ok=True)
    out = {
        "backtest": "NHL_V2_MATCHUP_CHALLENGER", "issue": 2447,
        "scope": "HISTORICAL_ONLY_NOT_THE_OCT8_NOV30_2026_EVALUATION_WINDOW",
        "protocol": {"dev": DEV, "validation": VAL, "test_locked": TEST, "max_attempts": 8,
                     "attempts_run": len(log), "selection_rule": "min mean(val logloss model - close) over 3 markets"},
        "sources": {"odds": "flancast90/sportsbookreview-scraper@1a820e50 data/nhl_archive_10Y.json",
                    "odds_blob": SOURCE_BLOB, "pbp": "sportsdataverse/fastRhockey-data nhl/json/*.json",
                    "n_pbp_games": len(games)},
        "inputs_not_available_free": ["historical injury reports (no free point-in-time archive found)",
                                      "pre-game 'expected' goalie reports; actual starter used as proxy for confirmed starter"],
        "attempt_log": log, "chosen_attempt": chosen["id"], "final": final,
        "authority": {"play": False, "promotion": False, "production_wired": False},
    }
    a.output.write_text(json.dumps(out, indent=1, default=str) + "\n")
    for m, v in final["TEST_2021_LOCKED"].items():
        print("TEST", m, v["n"], v["verdict"], round(v["brier_model"], 5), round(v["brier_close_novig"], 5),
              round(v["logloss_model"], 5), round(v["logloss_close_novig"], 5), v["bets_ev_ge_2pct"], v["roi_at_logged_price"])


if __name__ == "__main__":
    main()
