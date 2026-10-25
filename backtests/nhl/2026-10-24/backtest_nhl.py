"""NHL overnight historical backtest (#2447 protocol, 2026-10-24).

HISTORICAL ONLY. Does not read, write or bear on the frozen Oct 8 - Nov 30 2026
NHL evaluation window, its ledger or its verdict. Changes no model math,
thresholds or promotion state.

Source: flancast90/sportsbookreview-scraper @ 1a820e50, data/nhl_archive_10Y.json
(Git blob 9dd97a3064b8001039e3cc06a4b4657f338a4045). Calendar-date clock only.

Models scored (both fixed BEFORE looking at any holdout result):
  A. FROZEN_COEF_PIT: the frozen NHL_RATE_V1 coefficients from
     artifacts/nhl/nhl_rate_v1_freeze.json, unchanged, fed with POINT-IN-TIME
     team GF/GA per game built from strictly earlier calendar dates. The shipped
     card's static 2025-26 priors are NOT usable historically (they would be
     future data), and the archive has no shots, so shot_share is held at the
     neutral 0.5. Regulation Poisson + OT/SO coin-flip goal, exactly as
     sportsedge/nhl_rate_v1_card.final_score_distribution.
  B. WF_POISSON: same feature family (PIT GF, opp PIT GA, home), Poisson GLM on
     regulation goals refit walk-forward on all strictly earlier seasons only.

Holdout = latest season in the archive (2021 = 2021-22). Earlier seasons are
reported as walk-forward development folds.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from metrics import (EV_THRESHOLD, american_to_decimal, git_blob_sha1, implied,  # noqa: E402
                     market_report, no_vig)

REPO = HERE.parents[2]
SOURCE_BLOB = "9dd97a3064b8001039e3cc06a4b4657f338a4045"
SOURCE_COMMIT = "1a820e50c6fbd0276cde073c22bfffae78930868"
HOLDOUT = 2021
FIRST_SCORED = 2012          # 2011 is warm-up only
TEAM_WINDOW = 60             # declared, untuned
SHRINK_K = 20.0              # declared, untuned
MIN_TEAM_GAMES = 10
LEAGUE_WINDOW = 1000
TOTALS_OVERROUND = 0.045     # archive carries ONE totals price (under side); declared assumption
NEUTRAL_SHOT_SHARE = 0.5

ALIASES = {"St.Louis": "Blues", "Phoenix": "Coyotes", "Arizonas": "Coyotes",
           "SeattleKraken": "Kraken", "Tampa Bay": "Lightning", "Tampa": "Lightning",
           "WinnipegJets": "Jets", "NY Islanders": "Islanders"}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def load(path: Path):
    raw = path.read_bytes()
    sha = git_blob_sha1(raw)
    if sha != SOURCE_BLOB:
        raise SystemExit(f"SOURCE_BLOB_MISMATCH {sha}")
    data = json.loads(raw)
    rows, dropped, seen = [], defaultdict(int), set()
    for x in data:
        h = ALIASES.get(str(x["home_team"]), str(x["home_team"]))
        a = ALIASES.get(str(x["away_team"]), str(x["away_team"]))
        hf, af = _int(x.get("home_final")), _int(x.get("away_final"))
        per = [_int(x.get(f"{s}_{p}Period")) for s in ("home", "away") for p in ("1st", "2nd", "3rd")]
        if h in ("0", "") or a in ("0", "") or h == a or hf is None or af is None or None in per:
            dropped["bad_identity_or_score"] += 1
            continue
        key = (int(x["date"]), h, a)
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        rows.append({"season": int(x["season"]), "day": int(x["date"]), "home": h, "away": a,
                     "hf": hf, "af": af, "hreg": sum(per[:3]), "areg": sum(per[3:]), "raw": x})
    rows.sort(key=lambda r: (r["day"], r["home"]))
    return rows, sha, len(data), dict(dropped)


def build_features(rows):
    """Attach PIT features using only games on strictly earlier calendar dates.

    Leakage guard: all of a day's games are featurized before any of that day's
    results enter the state.
    """
    hist = defaultdict(lambda: deque(maxlen=TEAM_WINDOW))   # team -> (gf, ga)
    league = deque(maxlen=LEAGUE_WINDOW)                    # per-team goals (final)
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j]["day"] == rows[i]["day"]:
            j += 1
        lg = (sum(league) / len(league)) if len(league) >= 200 else None
        for g in rows[i:j]:
            g["feat"] = None
            hh, ha = hist[g["home"]], hist[g["away"]]
            if lg is None or min(len(hh), len(ha)) < MIN_TEAM_GAMES:
                continue

            def shr(vals):
                n = len(vals)
                return lg + (sum(vals) / n - lg) * n / (n + SHRINK_K)
            g["feat"] = {"lg": lg,
                         "h_gf": shr([v[0] for v in hh]), "h_ga": shr([v[1] for v in hh]),
                         "a_gf": shr([v[0] for v in ha]), "a_ga": shr([v[1] for v in ha]),
                         "max_input_day": max(v[2] for v in list(hh) + list(ha))}
        for g in rows[i:j]:
            hist[g["home"]].append((g["hf"], g["af"], g["day"]))
            hist[g["away"]].append((g["af"], g["hf"], g["day"]))
            league.extend([g["hf"], g["af"]])
        i = j
    leaks = sum(1 for g in rows if g["feat"] and g["feat"]["max_input_day"] >= g["day"])
    return leaks


def frozen_lambdas(g, P):
    f = g["feat"]
    def lam(gf, oga, home):
        eta = (P["intercept"] + P["offense_xg"] * gf + P["opponent_xga"] * oga
               + P["shot_share"] * NEUTRAL_SHOT_SHARE + P["rest"] * 1.0 + P["home_ice"] * home)
        return math.exp(max(-8.0, min(4.0, eta)))
    return lam(f["h_gf"], f["a_ga"], 1.0), lam(f["a_gf"], f["h_ga"], 0.0)


def design(g):
    f = g["feat"]
    return ([1.0, f["h_gf"], f["a_ga"], 1.0], [1.0, f["a_gf"], f["h_ga"], 0.0])


def fit_poisson(X, y, iters=50):
    X, y = np.asarray(X), np.asarray(y, float)
    w = np.zeros(X.shape[1]); w[0] = math.log(max(y.mean(), 1e-3))
    for _ in range(iters):
        mu = np.exp(X @ w)
        step = np.linalg.solve((X * mu[:, None]).T @ X + 1e-9 * np.eye(len(w)), X.T @ (y - mu))
        w += step
        if np.max(np.abs(step)) < 1e-10:
            break
    return w


def score_dist(lh, la, kmax=20):
    ph = [math.exp(-lh)]; pa = [math.exp(-la)]
    for k in range(1, kmax + 1):
        ph.append(ph[-1] * lh / k); pa.append(pa[-1] * la / k)
    d = defaultdict(float)
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            p = pi * pj
            if i == j:
                d[(i + 1, j)] += 0.5 * p; d[(i, j + 1)] += 0.5 * p
            else:
                d[(i, j)] += p
    z = sum(d.values())
    return {k: v / z for k, v in d.items()}


def p_over(dist, line):
    o = sum(p for (h, a), p in dist.items() if h + a > line)
    u = sum(p for (h, a), p in dist.items() if h + a < line)
    return o, u


def p_home_cover(dist, home_spread):
    c = sum(p for (h, a), p in dist.items() if h - a + home_spread > 0)
    n = sum(p for (h, a), p in dist.items() if h - a + home_spread < 0)
    return c, n


def totals_two_sided(under_odds):
    """Archive gives only the under price. Derive no-vig and an over price
    under a declared constant overround."""
    pu = implied(under_odds)
    po_vig = (1 + TOTALS_OVERROUND) - pu
    if not 0.05 < po_vig < 0.95:
        return None
    return {"p_under_nv": pu / (1 + TOTALS_OVERROUND), "over_dec": 1 / po_vig,
            "under_dec": american_to_decimal(under_odds)}


def evaluate(rows, model_name, lam_fn):
    out = defaultdict(list)   # (market, season) -> rows
    for g in rows:
        if g["feat"] is None or g["season"] < FIRST_SCORED:
            continue
        lams = lam_fn(g)
        if lams is None:
            continue
        dist = score_dist(*lams)
        x, s = g["raw"], g["season"]
        hw = sum(p for (h, a), p in dist.items() if h > a)
        y_home = 1 if g["hf"] > g["af"] else 0
        # ---- moneyline: evaluate vs close; bet at OPEN price; CLV in no-vig prob
        hc, ac = x.get("home_close_ml"), x.get("away_close_ml")
        ho, ao = x.get("home_open_ml"), x.get("away_open_ml")
        if hc and ac and abs(hc) >= 100 and abs(ac) >= 100:
            pc_h, _ = no_vig(hc, ac)
            r = {"p_model": hw, "p_close": pc_h, "y": y_home, "bet_ev": None}
            if ho and ao and abs(ho) >= 100 and abs(ao) >= 100:
                po_h, _ = no_vig(ho, ao)
                ev_h = hw * american_to_decimal(ho) - 1
                ev_a = (1 - hw) * american_to_decimal(ao) - 1
                if max(ev_h, ev_a) >= EV_THRESHOLD:
                    home_side = ev_h >= ev_a
                    r.update(bet_ev=max(ev_h, ev_a),
                             bet_dec=american_to_decimal(ho if home_side else ao),
                             bet_won=(y_home if home_side else 1 - y_home),
                             clv=(pc_h - po_h) if home_side else (po_h - pc_h))
            out[("moneyline", s)].append(r)
        # ---- totals: evaluate at CLOSE line; bet at OPEN line/price; CLV only when lines equal
        L, uo = x.get("close_over_under"), x.get("close_over_under_odds")
        tot = g["hf"] + g["af"]
        if L and uo and 3.5 <= L <= 8.5 and tot != L:
            tw = totals_two_sided(uo)
            if tw:
                po, pu = p_over(dist, L)
                r = {"p_model": po / (po + pu), "p_close": 1 - tw["p_under_nv"],
                     "y": int(tot > L), "bet_ev": None}
                OL, ouo = x.get("open_over_under"), x.get("open_over_under_odds")
                if OL and ouo and 3.5 <= OL <= 8.5:
                    tw_o = totals_two_sided(ouo)
                    if tw_o:
                        o2, u2 = p_over(dist, OL)
                        ev_o = o2 * tw_o["over_dec"] + (1 - o2 - u2) - 1
                        ev_u = u2 * tw_o["under_dec"] + (1 - o2 - u2) - 1
                        if max(ev_o, ev_u) >= EV_THRESHOLD:
                            over = ev_o >= ev_u
                            won = None if tot == OL else int((tot > OL) == over)
                            clv = None
                            if OL == L:
                                pov_close, pov_open = 1 - tw["p_under_nv"], 1 - tw_o["p_under_nv"]
                                clv = (pov_close - pov_open) if over else (pov_open - pov_close)
                            r.update(bet_ev=max(ev_o, ev_u),
                                     bet_dec=tw_o["over_dec"] if over else tw_o["under_dec"],
                                     bet_won=won, clv=clv)
                out[("totals", s)].append(r)
        # ---- puck line: close only (no open PL in archive) -> bet at close, CLV n/a
        sp, hso, aso = x.get("home_close_spread"), x.get("home_close_spread_odds"), x.get("away_close_spread_odds")
        if sp in (-1.5, 1.5) and hso and aso and abs(hso) >= 100 and abs(aso) >= 100:
            pc_h, _ = no_vig(hso, aso)
            c, n = p_home_cover(dist, sp)
            yc = int(g["hf"] - g["af"] + sp > 0)
            r = {"p_model": c / (c + n), "p_close": pc_h, "y": yc, "bet_ev": None}
            ev_h = c * american_to_decimal(hso) - 1
            ev_a = n * american_to_decimal(aso) - 1
            if max(ev_h, ev_a) >= EV_THRESHOLD:
                hs = ev_h >= ev_a
                r.update(bet_ev=max(ev_h, ev_a), bet_dec=american_to_decimal(hso if hs else aso),
                         bet_won=yc if hs else 1 - yc, clv=None)
            out[("puck_line", s)].append(r)
    return out


def summarize(out, model):
    res = {}
    for market, unit in (("moneyline", "no-vig prob, close minus open (bet at open)"),
                         ("totals", "no-vig prob at same line, close minus open (bet at open)"),
                         ("puck_line", "n/a - archive has close puck line only; bets at close")):
        seasons = sorted(s for (m, s) in out if m == market)
        dev = [r for s in seasons if s != HOLDOUT for r in out[(market, s)]]
        res[market] = {
            "holdout_season": HOLDOUT,
            "holdout": market_report(out.get((market, HOLDOUT), []), clv_unit=unit),
            "walk_forward_dev_pooled": market_report(dev, clv_unit=unit),
            "per_season": {s: market_report(out[(market, s)], clv_unit=unit) for s in seasons},
        }
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=HERE / "results.json")
    a = ap.parse_args(argv)
    rows, sha, raw_n, dropped = load(a.source)
    leaks = build_features(rows)
    if leaks:
        raise SystemExit(f"LEAKAGE_CHECK_FAILED {leaks}")
    P = json.loads((REPO / "artifacts/nhl/nhl_rate_v1_freeze.json").read_text())["parameters"]
    attempts = []

    # Model A: frozen coefficients, PIT inputs
    attempts.append({"id": 1, "model": "FROZEN_COEF_PIT", "note": "frozen v1 coefs, PIT GF/GA, shot_share=0.5"})
    out_a = evaluate(rows, "FROZEN_COEF_PIT", lambda g: frozen_lambdas(g, P))

    # Model B: walk-forward Poisson GLM, refit per season on strictly earlier seasons
    coefs = {}
    seasons = sorted({g["season"] for g in rows})
    for s in seasons:
        train = [g for g in rows if g["feat"] and g["season"] < s]
        if len(train) < 500:
            continue
        X, y = [], []
        for g in train:
            xh, xa = design(g)
            X += [xh, xa]; y += [g["hreg"], g["areg"]]
        coefs[s] = fit_poisson(X, y)
    attempts.append({"id": 2, "model": "WF_POISSON", "note": "refit per season on prior seasons only; holdout never in train",
                     "coefs_by_test_season": {s: [round(v, 5) for v in w] for s, w in coefs.items()}})

    def lam_b(g):
        w = coefs.get(g["season"])
        if w is None:
            return None
        xh, xa = design(g)
        return math.exp(float(np.dot(w, xh))), math.exp(float(np.dot(w, xa)))
    out_b = evaluate(rows, "WF_POISSON", lam_b)

    report = {
        "backtest": "NHL_OVERNIGHT_20261024", "issue": 2447,
        "scope": "HISTORICAL_ONLY_NOT_THE_OCT8_NOV30_2026_EVALUATION_WINDOW",
        "source": {"repo": "flancast90/sportsbookreview-scraper", "commit": SOURCE_COMMIT,
                   "path": "data/nhl_archive_10Y.json", "git_blob_sha1": sha,
                   "raw_rows": raw_n, "normalized_rows": len(rows), "dropped": dropped,
                   "clock": "CALENDAR_DATE_ONLY", "book_identity": "UNKNOWN",
                   "market_authority": "INDICATIVE_NOT_ADMITTED"},
        "leakage_check": {"features_from_strictly_prior_dates": True, "violations": leaks},
        "declared_constants": {"TEAM_WINDOW": TEAM_WINDOW, "SHRINK_K": SHRINK_K,
                               "MIN_TEAM_GAMES": MIN_TEAM_GAMES, "LEAGUE_WINDOW": LEAGUE_WINDOW,
                               "TOTALS_OVERROUND_ASSUMED": TOTALS_OVERROUND,
                               "NEUTRAL_SHOT_SHARE": NEUTRAL_SHOT_SHARE, "EV_THRESHOLD": EV_THRESHOLD},
        "caveats": [
            "Totals price in archive is one-sided (empirically the UNDER price); no-vig and over price use a declared 4.5% overround.",
            "Puck line exists only 2014+ and only at close; ROI is at close and CLV is not computable.",
            "Model A cannot use the shipped static 2025-26 priors historically; it is the frozen coefficient vector on PIT inputs with no shots data.",
            "Verdict rule: BEATS_CLOSE only if holdout Brier AND log-loss both beat close no-vig; n<200 => INSUFFICIENT_DATA.",
        ],
        "attempt_log": attempts,
        "models": {"FROZEN_COEF_PIT": summarize(out_a, "A"), "WF_POISSON": summarize(out_b, "B")},
        "authority": {"play": False, "promotion": False, "model_math_changed": False},
    }
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    for m, res in report["models"].items():
        for mk, r in res.items():
            h = r["holdout"]
            print(m, mk, h["n"], h.get("verdict"), round(h.get("brier_model", 0), 5),
                  round(h.get("brier_close_novig", 0), 5), h.get("bets_ev_ge_2pct"), h.get("roi_at_logged_price"),
                  h.get("mean_clv"))


if __name__ == "__main__":
    main()
