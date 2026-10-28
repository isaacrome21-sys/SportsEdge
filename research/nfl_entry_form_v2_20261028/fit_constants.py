"""NFL_ENTRY_FORM_V2 — build-stage fit of the §7.4 constants.

Fits the construction's OLS mappings ONCE on pooled 2020-2025 design
data (PREREG_DRAFT §7.4: coefficients "as fitted on 2020-2025 design
data"; §3: "fitted once at freeze on 2020-2025 design data" — this
build-stage fit is that fit executed early so the §7 package can be
built and landing-checked; the freeze act re-runs and re-pins it on the
exact frozen head, and the freeze fit governs).

Specs (DESIGN §4.1 spec B / §4.2):
  core margin : margin        ~ EPA margin + form divergence
  core total  : total         ~ EPA total + form divergence
  veto margin : margin-close  ~ form divergence + QB delta (home/away)
                                + rest differential
  veto total  : total-close   ~ form divergence + pace deviation
                                + wind + cold
Sigma per market = std of the core fit's residuals (ddof = n params,
the design screen's fit_ols), floored at 12.5 (PREREG_DRAFT §3).

Eligible rows: both teams >= 3 prior in-season REG games, features from
games strictly before (DesignWalk). DESIGN DATA ONLY — zero validation
credit. Writes fitted_constants.json beside this file and prints the
constants block for nfl_entry_form_v2_constants.py.
"""
import argparse
import json
import math
import os

import numpy as np

import design_data as dd
from sportsedge import nfl_entry_form_v2_constants as C


def fit_ols(X, y):
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    return beta, float(np.std(resid, ddof=len(beta)))


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default=dd.default_games_path())
    ap.add_argument("--data-dir", default=dd.default_data_dir())
    ap.add_argument("--out", default=os.path.join(dd.HERE, "fitted_constants.json"))
    args = ap.parse_args()

    dd.ensure_parquets(args.data_dir)
    games = dd.load_games(args.games)
    walk = dd.DesignWalk(games, dd.load_team_week(args.data_dir),
                         dd.load_qb_week(args.data_dir))
    rows = []
    per_season = {}
    while True:
        item = walk.step()
        if item is None:
            break
        gm, feat, _ctx = item
        if (feat["home_prior_games"] >= C.MIN_PRIOR_REG_GAMES
                and feat["away_prior_games"] >= C.MIN_PRIOR_REG_GAMES):
            rows.append({**feat,
                         "season": int(gm.season),
                         "margin": float(gm.home_score - gm.away_score),
                         "total": float(gm.home_score + gm.away_score),
                         "mkt_margin": float(gm.spread_line),
                         "mkt_total": float(gm.total_line)})
            per_season[int(gm.season)] = per_season.get(int(gm.season), 0) + 1
    if len(rows) < 1000:
        raise SystemExit(f"only {len(rows)} eligible rows — refusing to fit")

    def col(name):
        return np.array([r[name] for r in rows], float)

    beta_m, sigma_m = fit_ols(
        np.column_stack([col("x_epa_margin"), col("x_form_margin")]), col("margin"))
    beta_t, sigma_t = fit_ols(
        np.column_stack([col("y_epa_total"), col("y_form_total")]), col("total"))
    beta_rm, _ = fit_ols(
        np.column_stack([col("x_form_margin"), col("x_qb_h"), col("x_qb_a"),
                         col("x_rest")]), col("margin") - col("mkt_margin"))
    beta_rt, _ = fit_ols(
        np.column_stack([col("y_form_total"), col("y_pace_dev"), col("y_wind"),
                         col("y_cold")]), col("total") - col("mkt_total"))

    out = {
        "evidence_state": "DESIGN ONLY — build-stage fit on pooled 2020-2025 "
                          "design data; zero validation credit; the freeze "
                          "fit governs (PREREG_DRAFT §3/§7.4)",
        "n_eligible_rows": len(rows),
        "per_season": per_season,
        "pins": {"games_csv_gz_sha256": dd.GAMES_SHA256,
                 "weekly_parquets": "sha256-verified against PINS.json "
                                    "before use (ensure_parquets)"},
        "core_fit": {
            "SPREAD": {"intercept": beta_m[0], "epa_margin": beta_m[1],
                       "form_divergence": beta_m[2]},
            "TOTAL": {"intercept": beta_t[0], "epa_total": beta_t[1],
                      "form_divergence": beta_t[2]},
        },
        "residual_fit": {
            "SPREAD": {"intercept": beta_rm[0], "form_divergence": beta_rm[1],
                       "qb_home": beta_rm[2], "qb_away": beta_rm[3],
                       "rest": beta_rm[4]},
            "TOTAL": {"intercept": beta_rt[0], "form_divergence": beta_rt[1],
                      "pace_deviation": beta_rt[2], "wind": beta_rt[3],
                      "cold": beta_rt[4]},
        },
        "sigma_raw": {"SPREAD": sigma_m, "TOTAL": sigma_t},
        "sigma_fit": {"SPREAD": max(sigma_m, C.SIGMA_FLOOR),
                      "TOTAL": max(sigma_t, C.SIGMA_FLOOR)},
        "fireability": {
            m: {"sigma": max(s, C.SIGMA_FLOOR),
                "Phi(3/sigma)": norm_cdf(3.0 / max(s, C.SIGMA_FLOOR)),
                "Phi(5/sigma)": norm_cdf(5.0 / max(s, C.SIGMA_FLOOR))}
            for m, s in (("SPREAD", sigma_m), ("TOTAL", sigma_t))},
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out, indent=1))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
