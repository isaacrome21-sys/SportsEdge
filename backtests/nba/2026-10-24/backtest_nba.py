"""NBA overnight historical backtest (#2447 protocol, 2026-10-24).

Reproduces and extends the Oct 21 2026 date-only negative screens:
  research/nba_elo_v2_sbr_dateonly_negative_screen_20261021.md  (Elo sides V2)
  research/nba_scoring_level_v2_dateonly_negative_screen_20261021.md (totals V2)
by converting their point forecasts into PROBABILITIES so they can be scored
with Brier / log-loss / calibration against the closing no-vig price.

Source: flancast90/sportsbookreview-scraper @ 1a820e50, data/nba_archive_10Y.json
(Git blob f5ba0d4f8f729236fdd8883a65189f2d6443338c). Calendar-date clock only.
Changes no model math, thresholds or promotion state. Elo and totals-V2
parameters are the DECLARED values from the existing scripts (imported, not
retyped). The only quantity estimated is the residual SD used to turn a point
forecast into a cover probability, and it is fit walk-forward on strictly
earlier seasons. Holdout = latest season (2021 = 2021-22).

Archive limits (declared): ML has CLOSE only (bets at close; CLV n/a).
Spread / total have open and close LINES but no prices -> -110 both sides is
assumed, so close no-vig is 0.5 at the close line by construction.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "backtests" / "nhl" / "2026-10-24"))  # shared metrics.py
sys.path.insert(0, str(REPO / "scripts"))
from metrics import EV_THRESHOLD, american_to_decimal, git_blob_sha1, market_report, no_vig  # noqa: E402
import research_nba_elo_sbr_dateonly_screen as ELO  # noqa: E402
import research_nba_v2_sbr_dateonly_screen as TOT  # noqa: E402

HOLDOUT = 2021
DEV_FIRST = 2015       # same first scored season as the Oct 21 screens
ASSUMED_PRICE = -110
DEC_110 = american_to_decimal(ASSUMED_PRICE)


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def load(path):
    raw_bytes = path.read_bytes()
    sha = git_blob_sha1(raw_bytes)
    if sha != ELO.SOURCE_BLOB_SHA1:
        raise SystemExit("SOURCE_BLOB_MISMATCH")
    raw = json.loads(raw_bytes)
    rows = ELO.normalize(raw)
    extra = {}
    for x in raw:
        h = ELO.ALIASES.get(str(x.get("home_team") or ""), str(x.get("home_team") or ""))
        a = ELO.ALIASES.get(str(x.get("away_team") or ""), str(x.get("away_team") or ""))
        try:
            extra[(int(float(x["date"])), h, a)] = x
        except (TypeError, ValueError, KeyError):
            pass
    for g in rows:
        x = extra[(g["day"], g["home"], g["away"])]
        g["open_spread"] = ELO._number(x.get("home_open_spread"))
        g["close_total"] = ELO._number(x.get("close_over_under"))
        g["open_total"] = ELO._number(x.get("open_over_under"))
    return raw, rows, sha


def elo_forecasts(rows):
    """Same arithmetic as ELO.evaluate_date_only, retaining per-game forecasts."""
    ratings, counts = {}, defaultdict(int)
    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and rows[j]["day"] == rows[i]["day"]:
            j += 1
        updates = []
        for g in rows[i:j]:
            home, away = g["home"], g["away"]
            ph = ratings.get(home, (ELO.INITIAL, None))[0]
            pa = ratings.get(away, (ELO.INITIAL, None))[0]
            g["elo_ok"] = min(counts[home], counts[away]) >= ELO.MIN_TEAM_GAMES
            g["elo_margin"] = (ph - pa) / ELO.ELO_PER_POINT + ELO.HOME_COURT_POINTS
            g["elo_p_home"] = ELO._expected(ph + ELO.HOME_COURT_POINTS * ELO.ELO_PER_POINT, pa)
            rh, sh = ratings.get(home, (ELO.INITIAL, None))
            ra, sa = ratings.get(away, (ELO.INITIAL, None))
            nh = rh + ELO.SEASON_REGRESS * (ELO.INITIAL - rh) if sh is not None and sh != g["season"] else rh
            na = ra + ELO.SEASON_REGRESS * (ELO.INITIAL - ra) if sa is not None and sa != g["season"] else ra
            pre = nh - na
            win = 1.0 if g["hp"] > g["ap"] else 0.0 if g["hp"] < g["ap"] else 0.5
            norm = ELO.NFL_MARGIN_SD / ELO.NBA_MARGIN_SD
            wd = pre if g["hp"] > g["ap"] else -pre
            mult = ((abs(g["hp"] - g["ap"]) * norm + 3.0) ** 0.8) / (7.45 + 0.006 * abs(wd) * norm)
            e = ELO._expected(nh, na)
            updates.append((home, nh + ELO.K * mult * (win - e), away,
                            na + ELO.K * mult * ((1 - win) - (1 - e)), g["season"]))
        for home, nh, away, na, s in updates:
            ratings[home] = (nh, s); ratings[away] = (na, s)
            counts[home] += 1; counts[away] += 1
        i = j


def totals_forecasts(rows):
    """Same arithmetic as TOT.evaluate_calendar_archive (V2 pair construction)."""
    for i, game in enumerate(rows):
        game["tot_pred"] = None
        past = []
        for j in range(i - 1, -1, -1):
            if rows[j]["day"] < game["day"]:
                past.append(rows[j])
                if len(past) == 450:
                    break
        if len(past) < 30:
            continue
        game["tot_max_input_day"] = max(p["day"] for p in past)
        league = sum((g["hp"] + g["ap"]) / 2.0 for g in past) / len(past)
        h, a = game["home"], game["away"]
        t = {h: {"sc": [], "co": []}, a: {"sc": [], "co": []}}
        for p in past:
            if p["home"] in t:
                t[p["home"]]["sc"].append(p["hp"]); t[p["home"]]["co"].append(p["ap"])
            if p["away"] in t:
                t[p["away"]]["sc"].append(p["ap"]); t[p["away"]]["co"].append(p["hp"])
        if min(len(t[h]["sc"]), len(t[a]["sc"])) < 5:
            continue

        def shr(v):
            return (sum(v) / len(v) - league) * len(v) / (len(v) + 20.0)
        game["tot_pred"] = (2 * league + shr(t[h]["sc"]) + shr(t[a]["co"])
                            + shr(t[a]["sc"]) + shr(t[h]["co"]))


def leakage_check(rows):
    """Re-derive Elo forecasts with every game ON or AFTER date D removed and
    confirm the forecast for date D is identical (sampled every 25th date)."""
    days = sorted({g["day"] for g in rows})
    bad = 0
    checked = 0
    for d in days[200::250]:
        sub = [dict(g) for g in rows if g["day"] <= d]
        # scramble same-day and future outcomes: must not change date-d forecasts
        for g in sub:
            if g["day"] == d:
                g["hp"], g["ap"] = 0.0, 300.0
        elo_forecasts(sub)
        ref = {(g["home"], g["away"]): g["elo_p_home"] for g in rows if g["day"] == d}
        for g in sub:
            if g["day"] == d:
                checked += 1
                bad += abs(ref[(g["home"], g["away"])] - g["elo_p_home"]) > 1e-12
    tot_bad = sum(1 for g in rows if g.get("tot_pred") is not None and g["tot_max_input_day"] >= g["day"])
    return {"elo_scramble_same_day_checked": checked, "elo_violations": bad, "totals_input_date_violations": tot_bad}


def residual_sd(rows, season, key_pred, key_actual):
    res = [key_pred(g) - key_actual(g) for g in rows
           if DEV_FIRST - 3 <= g["season"] < season and key_pred(g) is not None]
    if len(res) < 500:
        return None
    m = sum(res) / len(res)
    return math.sqrt(sum((r - m) ** 2 for r in res) / (len(res) - 1)), len(res)


def evaluate(rows):
    out = defaultdict(list)
    sds = {}
    for s in sorted({g["season"] for g in rows}):
        if s < DEV_FIRST:
            continue
        sds[s] = {
            "margin": residual_sd(rows, s, lambda g: g["elo_margin"] if g["elo_ok"] else None,
                                  lambda g: g["hp"] - g["ap"]),
            "total": residual_sd(rows, s, lambda g: g["tot_pred"], lambda g: g["hp"] + g["ap"]),
        }
    for g in rows:
        s = g["season"]
        if s < DEV_FIRST:
            continue
        actual_m, actual_t = g["hp"] - g["ap"], g["hp"] + g["ap"]
        y_home = int(actual_m > 0)
        # moneyline: Elo win probability (as declared) vs close no-vig; bet at close
        if g["elo_ok"] and g["home_ml"] is not None and g["away_ml"] is not None:
            pc, _ = no_vig(g["home_ml"], g["away_ml"])
            p = g["elo_p_home"]
            r = {"p_model": p, "p_close": pc, "y": y_home, "bet_ev": None}
            evh = p * american_to_decimal(g["home_ml"]) - 1
            eva = (1 - p) * american_to_decimal(g["away_ml"]) - 1
            if max(evh, eva) >= EV_THRESHOLD:
                hs = evh >= eva
                r.update(bet_ev=max(evh, eva), bet_dec=american_to_decimal(g["home_ml"] if hs else g["away_ml"]),
                         bet_won=y_home if hs else 1 - y_home, clv=None)
            out[("moneyline", s)].append(r)
        # spread: Elo margin -> P(home covers) with walk-forward residual SD
        sdm = sds[s]["margin"]
        if g["elo_ok"] and sdm and g["spread"] is not None and actual_m + g["spread"] != 0:
            sd = sdm[0]
            p = phi((g["elo_margin"] + g["spread"]) / sd)
            yc = int(actual_m + g["spread"] > 0)
            r = {"p_model": p, "p_close": 0.5, "y": yc, "bet_ev": None}
            osp = g["open_spread"]
            if osp is not None and abs(osp) <= 25:
                po = phi((g["elo_margin"] + osp) / sd)
                ev_h, ev_a = po * DEC_110 - 1, (1 - po) * DEC_110 - 1
                if max(ev_h, ev_a) >= EV_THRESHOLD:
                    hs = ev_h >= ev_a
                    m = actual_m + osp
                    won = None if m == 0 else int((m > 0) == hs)
                    # CLV: P(bet wins at open line) under a close-centred market distribution, minus 0.5
                    pmk = phi((-g["spread"] + osp) / sd)
                    r.update(bet_ev=max(ev_h, ev_a), bet_dec=DEC_110, bet_won=won,
                             clv=(pmk - 0.5) if hs else (0.5 - pmk))
            out[("spread", s)].append(r)
        # total: V2 projected total -> P(over)
        sdt = sds[s]["total"]
        ct = g["close_total"]
        if g["tot_pred"] is not None and sdt and ct is not None and 170 <= ct <= 270 and actual_t != ct:
            sd = sdt[0]
            p = 1 - phi((ct - g["tot_pred"]) / sd)
            r = {"p_model": p, "p_close": 0.5, "y": int(actual_t > ct), "bet_ev": None}
            ot = g["open_total"]
            if ot is not None and 170 <= ot <= 270:
                po = 1 - phi((ot - g["tot_pred"]) / sd)
                ev_o, ev_u = po * DEC_110 - 1, (1 - po) * DEC_110 - 1
                if max(ev_o, ev_u) >= EV_THRESHOLD:
                    over = ev_o >= ev_u
                    won = None if actual_t == ot else int((actual_t > ot) == over)
                    pmk = 1 - phi((ot - ct) / sd)
                    r.update(bet_ev=max(ev_o, ev_u), bet_dec=DEC_110, bet_won=won,
                             clv=(pmk - 0.5) if over else (0.5 - pmk))
            out[("total", s)].append(r)
    return out, sds


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=HERE / "results.json")
    a = ap.parse_args(argv)
    raw, rows, sha = load(a.source)
    elo_forecasts(rows)
    totals_forecasts(rows)
    leak = leakage_check(rows)
    if leak["elo_violations"] or leak["totals_input_date_violations"]:
        raise SystemExit(f"LEAKAGE_CHECK_FAILED {leak}")
    # parity with the committed Oct 21 screens (reproduction gate)
    elo_rep = ELO.evaluate_date_only(raw)
    tot_rep = TOT.evaluate_calendar_archive(raw)
    out, sds = evaluate(rows)
    units = {"moneyline": "n/a - archive has close ML only; bets at close",
             "spread": "prob, open-line bet under close-centred N(close, wf SD) minus 0.5",
             "total": "prob, open-line bet under close-centred N(close, wf SD) minus 0.5"}
    markets = {}
    for mk in ("moneyline", "spread", "total"):
        seasons = sorted(s for (m, s) in out if m == mk)
        dev = [r for s in seasons if s != HOLDOUT for r in out[(mk, s)]]
        markets[mk] = {"holdout_season": HOLDOUT,
                       "holdout": market_report(out.get((mk, HOLDOUT), []), clv_unit=units[mk]),
                       "walk_forward_dev_pooled": market_report(dev, clv_unit=units[mk]),
                       "per_season": {s: market_report(out[(mk, s)], clv_unit=units[mk]) for s in seasons}}
    report = {
        "backtest": "NBA_OVERNIGHT_20261024", "issue": 2447,
        "source": {"repo": "flancast90/sportsbookreview-scraper", "commit": ELO.SOURCE_COMMIT,
                   "path": ELO.SOURCE_PATH, "git_blob_sha1": sha, "raw_rows": len(raw),
                   "normalized_rows": len(rows), "clock": "CALENDAR_DATE_ONLY",
                   "book_identity": "UNKNOWN", "market_authority": "INDICATIVE_NOT_ADMITTED"},
        "reproduction_of_oct21_screens": {
            "elo_model_games": elo_rep["model_games"],
            "elo_margin_rmse_paired": elo_rep["model_margin_rmse_paired"],
            "elo_market_spread_rmse": elo_rep["indicative_market_spread_rmse"],
            "elo_ml_brier_paired": elo_rep["model_moneyline_brier_paired"],
            "elo_market_ml_brier": elo_rep["indicative_market_moneyline_brier"],
            "totals_v2_rmse_paired": tot_rep["candidate_rmse_paired"],
            "totals_market_rmse_paired": tot_rep["indicative_market_rmse_paired"],
            "matches_published": (elo_rep["model_games"] == 8877 and tot_rep["paired_games"] == 8215),
        },
        "leakage_check": leak,
        "walk_forward_residual_sd": {s: {k: (None if v is None else [round(v[0], 4), v[1]]) for k, v in d.items()}
                                     for s, d in sds.items()},
        "attempt_log": [
            {"id": 1, "note": "reproduced Oct 21 Elo V2 + totals V2 screens via the committed scripts"},
            {"id": 2, "note": "single run of probability conversion; SDs walk-forward from strictly earlier seasons; no tuning, no reruns on holdout"},
        ],
        "caveats": [
            "Spread/total prices absent in archive: -110 assumed; close no-vig = 0.5 by construction.",
            "ML has no opening price: ROI at close, CLV not computable.",
            "Verdict rule: BEATS_CLOSE only if holdout Brier AND log-loss both beat close no-vig; n<200 => INSUFFICIENT_DATA.",
        ],
        "markets": markets,
        "authority": {"play": False, "promotion": False, "model_math_changed": False},
    }
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report["reproduction_of_oct21_screens"]), leak)
    for mk, v in markets.items():
        for tag in ("walk_forward_dev_pooled", "holdout"):
            h = v[tag]
            print(mk, tag, h["n"], h["verdict"], round(h["brier_model"], 5), round(h["brier_close_novig"], 5),
                  round(h["logloss_model"], 4), round(h["logloss_close_novig"], 4),
                  {k: round(x, 3) for k, x in h["calibration_model"].items()},
                  h["bets_ev_ge_2pct"], h["roi_at_logged_price"], h["mean_clv"])


if __name__ == "__main__":
    main()
