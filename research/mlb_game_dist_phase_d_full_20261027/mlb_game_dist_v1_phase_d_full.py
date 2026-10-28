#!/usr/bin/env python3
"""
MLB_GAME_DIST_V1 - Phase D design-phase accuracy walk-forward, FULL FIDELITY
(design section 3.1 folds and pass bar; section 2.2 run-expectancy model WITH
the starter/bullpen PIT decomposition implemented).

This is the full-fidelity re-run of the reduced-fidelity Phase D executed in
PR #2833 (research/backtest_workstream_20261027), which FAILED with PIT at
team level only. Everything except the PIT term is structurally identical to
that run (same folds, baselines, park handling, joint NB grid, metrics, pass
bar) so the fidelity delta is isolated. A team-level-PIT replica is scored in
the same pass on the identical data snapshot for the comparison table.

FULL-FIDELITY PIT (design 2.2), for team T facing opponent O:
  PIT_O = (exp_inn_S * starter_rate9_S + (9 - exp_inn_S) * bullpen_rate9_O) / 9
  - S = the pitcher who actually started for O (design 2.3).
  - starter_rate9_S: S's runs allowed per 27 outs in his strictly-prior
    STARTS, shrunk toward the fold-fit league RA9 with prior weight
    KS_OUTS=150 outs (50 IP) - "shrunk by innings pitched" (design 2.2).
    Starter history is seeded from every fit-window game (chronological
    replay) and accumulates in-season, strictly prior at all times.
  - exp_inn_S: S's mean innings per strictly-prior start, shrunk toward the
    fold-fit league mean starter innings with KS_STARTS=5 pseudo-starts,
    clamped to [1.0, 8.75].
  - S with < 3 prior starts in the data window is priced at the unknown
    prior (league RA9, league mean starter innings) - never omitted, never
    at face value (design 2.2).
  - bullpen_rate9_O: O's bullpen runs allowed per 27 outs, expanding
    strictly-prior within the test season, prior-season final bullpen RA9
    carried in as the mix prior while O has < 20 current-season games
    (mirroring the design's OFF carry-in rule), shrinkage prior weight
    KBP_OUTS=180 outs at the mix rate.
  - Rates are per-27-outs (per 9 IP) as the design's PIT formula states;
    PIT_O enters the same lambda slot the reduced run's per-game PIT rate
    occupied. Declared normalization, identical for both teams.
The shrinkage weights above are implementation constants declared a priori
in this header (the design specifies the shrinkage structure, not these
weights); exactly one configuration is run - nothing is tuned against the
test folds.

POINT-IN-TIME DISCIPLINE: games are processed in (date, gamePk) order;
every feature for a game is computed from games strictly before it in that
order; a game's own boxscore updates history only AFTER the game is scored
(a watermark assertion enforces this in code). Fold constants (league
level, league RA9, league bullpen RA9, league starter innings, home field,
NB dispersion, extra-innings share, base rate, Elo HFA) are fitted on the
fit window (seasons <= fit_end) only. Prior-season carry-ins use season
test-1 finals, always inside the fit window. The --audit mode re-runs the
2024 fold on a dataset truncated at 2024-12-31 and asserts every 2024
prediction is bit-identical to the full-data run (no future game can move
a past prediction).

Pass bar (design 3.1, exactly as applied in PR #2833): moneyline Brier AND
log loss must beat BOTH naive baselines (home base rate; simple Elo) on the
pooled folds; totals MAE and team-total MAE vs the league-average
baselines, pooled and per fold. Metrics against OUTCOMES ONLY - no
historical market baseline exists (Gap G4). DESIGN EVIDENCE ONLY.
"""
import json
import math
import os
import sys

import numpy as np

K_SHRINK = 20.0          # team OFF / replica PIT shrinkage (pseudo-games)
MAXR = 26
KS_OUTS = 150            # starter-rate prior weight (outs) = 50 IP
KS_STARTS = 5            # expected-innings prior weight (starts)
KBP_OUTS = 180           # bullpen-rate prior weight (outs) = 60 IP
MIN_STARTS = 3           # design 2.2 unknown-prior threshold
FOLDS = [(2022, 2023), (2023, 2024), (2024, 2025), (2025, 2026)]


def nb_pmf(mu, r, kmax=MAXR):
    from math import exp, lgamma, log
    out = []
    for k in range(kmax + 1):
        lp = (lgamma(k + r) - lgamma(r) - lgamma(k + 1)
              + r * log(r / (r + mu)) + (k * log(mu / (r + mu)) if k else 0.0))
        out.append(exp(lp))
    s = sum(out)
    return np.array([x / s for x in out])


def run(games, park_path, team_names, only_fold=None):
    games = sorted(games, key=lambda g: (g["date"], g["pk"]))
    pf_file = json.load(open(park_path))
    pf_by_team = {}
    for name, v in (pf_file.get("teams") or {}).items():
        if isinstance(v, dict) and "park_factor_runs" in v:
            pf_by_team[name] = float(v["park_factor_runs"])

    def park_factor(home_team_id):
        nm = team_names.get(str(home_team_id)) or team_names.get(home_team_id)
        return pf_by_team.get(nm, 1.0)

    def season_finals(season):
        off, pit, n, bpr, bpo = {}, {}, {}, {}, {}
        for g in games:
            if g["season"] != season:
                continue
            off[g["at"]] = off.get(g["at"], 0) + g["as_"]
            pit[g["at"]] = pit.get(g["at"], 0) + g["hs"]
            off[g["ht"]] = off.get(g["ht"], 0) + g["hs"]
            pit[g["ht"]] = pit.get(g["ht"], 0) + g["as_"]
            n[g["at"]] = n.get(g["at"], 0) + 1
            n[g["ht"]] = n.get(g["ht"], 0) + 1
            bpr[g["ht"]] = bpr.get(g["ht"], 0) + g["h_bp_runs"]
            bpo[g["ht"]] = bpo.get(g["ht"], 0) + g["h_bp_outs"]
            bpr[g["at"]] = bpr.get(g["at"], 0) + g["a_bp_runs"]
            bpo[g["at"]] = bpo.get(g["at"], 0) + g["a_bp_outs"]
        bp9 = {t: (27.0 * bpr[t] / bpo[t] if bpo.get(t) else None) for t in bpr}
        return ({t: off[t] / n[t] for t in n},
                {t: pit[t] / n[t] for t in n}, bp9)

    all_rows = []
    fold_reports = {}
    fold_preds = {}

    for fit_end, test_season in FOLDS:
        if only_fold is not None and test_season != only_fold:
            continue
        fit = [g for g in games if g["season"] <= fit_end]
        test = [g for g in games if g["season"] == test_season]
        L = float(np.mean([g["hs"] for g in fit] + [g["as_"] for g in fit]))
        home_ratio = np.mean([g["hs"] for g in fit]) / np.mean([g["as_"] for g in fit])
        home_log = 0.5 * math.log(home_ratio)
        base_rate = float(np.mean([1.0 if g["hs"] > g["as_"] else 0.0 for g in fit]))
        tg = np.array([g["hs"] for g in fit] + [g["as_"] for g in fit], dtype=float)
        var = tg.var()
        r_nb = float(tg.mean() ** 2 / max(var - tg.mean(), 0.05))
        one_run = [g for g in fit if abs(g["hs"] - g["as_"]) == 1]
        ex_share = float(np.mean([1.0 if g["hs"] > g["as_"] else 0.0 for g in one_run]))
        tot_runs = sum(g["hs"] + g["as_"] for g in fit)
        tot_outs = sum(g["h_tot_outs"] + g["a_tot_outs"] for g in fit)
        L_ra9 = 27.0 * tot_runs / tot_outs
        L_bp9 = 27.0 * sum(g["h_bp_runs"] + g["a_bp_runs"] for g in fit) / \
            sum(g["h_bp_outs"] + g["a_bp_outs"] for g in fit)
        L_ipstart = (sum(g["h_starter"]["outs"] + g["a_starter"]["outs"] for g in fit)
                     / (2.0 * len(fit))) / 3.0

        league_total = float(np.mean([g["hs"] + g["as_"] for g in fit]))
        poff, ppit, pbp = season_finals(test_season - 1)

        def elo_run(hfa_pts):
            elo = {}
            probs = {}
            for g in fit + test:
                rh = elo.get(g["ht"], 1500.0) + hfa_pts
                ra = elo.get(g["at"], 1500.0)
                ph = 1 / (1 + 10 ** (-(rh - ra) / 400))
                probs[g["pk"]] = ph
                y = 1.0 if g["hs"] > g["as_"] else 0.0
                elo[g["ht"]] = elo.get(g["ht"], 1500.0) + 20 * (y - ph)
                elo[g["at"]] = elo.get(g["at"], 1500.0) + 20 * ((1 - y) - (1 - ph))
            return probs

        best_hfa, best_ll, elo_probs = 0, 1e18, None
        for hfa in range(0, 61, 5):
            pr = elo_run(hfa)
            ll = -np.mean([math.log(min(max(pr[g["pk"]], 1e-9), 1 - 1e-9)) if g["hs"] > g["as_"]
                           else math.log(min(max(1 - pr[g["pk"]], 1e-9), 1 - 1e-9)) for g in fit])
            if ll < best_ll:
                best_ll, best_hfa, elo_probs = ll, hfa, pr

        # seed starter history from the whole fit window (chronological
        # replay); every seeded start is strictly prior to the test season
        starter_hist = {}
        for g in fit:
            for st in (g["h_starter"], g["a_starter"]):
                if st["pid"] is not None:
                    h = starter_hist.setdefault(st["pid"], [0, 0, 0])
                    h[0] += 1
                    h[1] += st["outs"]
                    h[2] += st["runs"]
        watermark = (fit[-1]["date"], fit[-1]["pk"]) if fit else None

        scored, allowed, played = {}, {}, {}
        bp_runs_cum, bp_outs_cum = {}, {}
        rows = []
        for g in test:
            assert watermark is None or watermark < (g["date"], g["pk"]), \
                "history watermark not strictly prior to scored game"

            def shrunk(t, table, prior_table):
                n = played.get(t, 0)
                mix = prior_table.get(t, L) if n < 20 else L
                return (table.get(t, 0.0) + K_SHRINK * mix) / (n + K_SHRINK)

            off_h = shrunk(g["ht"], scored, poff)
            off_a = shrunk(g["at"], scored, poff)
            pit_h_replica = shrunk(g["ht"], allowed, ppit)
            pit_a_replica = shrunk(g["at"], allowed, ppit)

            def bullpen9(t):
                n = played.get(t, 0)
                mix = (pbp.get(t) or L_bp9) if n < 20 else L_bp9
                r = bp_runs_cum.get(t, 0)
                o = bp_outs_cum.get(t, 0)
                return 27.0 * (r + (mix / 27.0) * KBP_OUTS) / (o + KBP_OUTS)

            def starter9(st):
                h = starter_hist.get(st["pid"])
                if h is None or h[0] < MIN_STARTS:
                    return L_ra9, L_ipstart, True
                n_s, outs_s, runs_s = h
                rate9 = 27.0 * (runs_s + (L_ra9 / 27.0) * KS_OUTS) / (outs_s + KS_OUTS)
                exp_inn = (outs_s / 3.0 + KS_STARTS * L_ipstart) / (n_s + KS_STARTS)
                exp_inn = min(max(exp_inn, 1.0), 8.75)
                return rate9, exp_inn, False

            def pit_full(opp_team, opp_starter):
                s_rate, s_inn, _u = starter9(opp_starter)
                bp = bullpen9(opp_team)
                return (s_inn * s_rate + (9.0 - s_inn) * bp) / 9.0, s_inn

            pit_h_full, inn_h = pit_full(g["ht"], g["h_starter"])
            pit_a_full, inn_a = pit_full(g["at"], g["a_starter"])
            _r, _i, unk_h = starter9(g["h_starter"])
            _r, _i, unk_a = starter9(g["a_starter"])

            sqrtpf = math.sqrt(park_factor(g["ht"]))

            def lam(off_t, pit_o, is_home):
                return (L * (off_t / L) * (L / pit_o)
                        * math.exp(home_log if is_home else -home_log) * sqrtpf)

            lam_h_full = lam(off_h, pit_a_full, True)
            lam_a_full = lam(off_a, pit_h_full, False)
            lam_h_red = lam(off_h, pit_a_replica, True)
            lam_a_red = lam(off_a, pit_h_replica, False)

            def win_prob(lh, la):
                grid = np.outer(nb_pmf(lh, r_nb), nb_pmf(la, r_nb))
                return float(
                    sum(grid[i, j] for i in range(MAXR + 1) for j in range(MAXR + 1) if i > j)
                    + sum(grid[i, i] for i in range(MAXR + 1)) * ex_share)

            y = 1.0 if g["hs"] > g["as_"] else 0.0
            row = dict(
                pk=g["pk"], season=test_season, y=y,
                p_full=win_prob(lam_h_full, lam_a_full),
                p_red=win_prob(lam_h_red, lam_a_red),
                p_base=base_rate, p_elo=elo_probs[g["pk"]],
                exp_total_full=lam_h_full + lam_a_full,
                exp_total_red=lam_h_red + lam_a_red,
                act_total=g["hs"] + g["as_"],
                lam_h_full=lam_h_full, lam_a_full=lam_a_full,
                lam_h_red=lam_h_red, lam_a_red=lam_a_red,
                hs=g["hs"], as_=g["as_"],
                exp_inn_h=inn_h, exp_inn_a=inn_a, unk_h=unk_h, unk_a=unk_a,
                base_total_exp=league_total,
                base_team_exp=float(L))
            rows.append(row)
            fold_preds[g["pk"]] = row["p_full"]

            for t, s_, a_, bpr, bpo in (
                    (g["ht"], g["hs"], g["as_"], g["h_bp_runs"], g["h_bp_outs"]),
                    (g["at"], g["as_"], g["hs"], g["a_bp_runs"], g["a_bp_outs"])):
                scored[t] = scored.get(t, 0) + s_
                allowed[t] = allowed.get(t, 0) + a_
                played[t] = played.get(t, 0) + 1
                bp_runs_cum[t] = bp_runs_cum.get(t, 0) + bpr
                bp_outs_cum[t] = bp_outs_cum.get(t, 0) + bpo
            for st in (g["h_starter"], g["a_starter"]):
                if st["pid"] is not None:
                    h = starter_hist.setdefault(st["pid"], [0, 0, 0])
                    h[0] += 1
                    h[1] += st["outs"]
                    h[2] += st["runs"]
            watermark = (g["date"], g["pk"])
        all_rows.extend(rows)

        def metrics(rs, key):
            p = np.array([min(max(r[key], 1e-9), 1 - 1e-9) for r in rs])
            yy = np.array([r["y"] for r in rs])
            return (float(np.mean((p - yy) ** 2)),
                    float(-np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p))))

        fb, fl = metrics(rows, "p_full")
        rb, rl = metrics(rows, "p_red")
        bb, bl = metrics(rows, "p_base")
        eb, el = metrics(rows, "p_elo")
        fold_reports[test_season] = dict(
            n=len(rows), L=float(L), r_nb=r_nb, L_ra9=float(L_ra9),
            L_bp9=float(L_bp9), L_ipstart=float(L_ipstart),
            brier_full=fb, ll_full=fl,
            brier_reduced_replica=rb, ll_reduced_replica=rl,
            brier_base=bb, ll_base=bl, brier_elo=eb, ll_elo=el,
            total_mae_full=float(np.mean([abs(r["exp_total_full"] - r["act_total"]) for r in rows])),
            total_mae_reduced_replica=float(np.mean([abs(r["exp_total_red"] - r["act_total"]) for r in rows])),
            total_mae_base=float(np.mean([abs(league_total - r["act_total"]) for r in rows])),
            team_total_mae_full=float(np.mean([abs(r["lam_h_full"] - r["hs"]) + abs(r["lam_a_full"] - r["as_"]) for r in rows]) / 2),
            team_total_mae_reduced_replica=float(np.mean([abs(r["lam_h_red"] - r["hs"]) + abs(r["lam_a_red"] - r["as_"]) for r in rows]) / 2),
            team_total_mae_base=float(np.mean([abs(L - r["hs"]) + abs(L - r["as_"]) for r in rows]) / 2),
            elo_hfa=best_hfa,
            unknown_starter_game_share=float(np.mean([r["unk_h"] or r["unk_a"] for r in rows])),
            mean_exp_inn=float(np.mean([r["exp_inn_h"] for r in rows] + [r["exp_inn_a"] for r in rows])))
    if only_fold is not None:
        return fold_preds

    def metrics(rs, key):
        p = np.array([min(max(r[key], 1e-9), 1 - 1e-9) for r in rs])
        yy = np.array([r["y"] for r in rs])
        return (float(np.mean((p - yy) ** 2)),
                float(-np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p))))

    fb, fl = metrics(all_rows, "p_full")
    rb, rl = metrics(all_rows, "p_red")
    bb, bl = metrics(all_rows, "p_base")
    eb, el = metrics(all_rows, "p_elo")
    dec = []
    srt = sorted(all_rows, key=lambda r: r["p_full"])
    for i in range(10):
        chunk = srt[i * len(srt) // 10:(i + 1) * len(srt) // 10]
        dec.append(dict(decile=i + 1, n=len(chunk),
                        mean_p=float(np.mean([r["p_full"] for r in chunk])),
                        realized=float(np.mean([r["y"] for r in chunk]))))
    return dict(
        folds=fold_reports,
        pooled=dict(
            n=len(all_rows), brier_full=fb, ll_full=fl,
            brier_reduced_replica=rb, ll_reduced_replica=rl,
            brier_base=bb, ll_base=bl, brier_elo=eb, ll_elo=el,
            total_mae_full=float(np.mean([abs(r["exp_total_full"] - r["act_total"]) for r in all_rows])),
            total_mae_reduced_replica=float(np.mean([abs(r["exp_total_red"] - r["act_total"]) for r in all_rows])),
            team_total_mae_full=float(np.mean([abs(r["lam_h_full"] - r["hs"]) + abs(r["lam_a_full"] - r["as_"]) for r in all_rows]) / 2),
            team_total_mae_reduced_replica=float(np.mean([abs(r["lam_h_red"] - r["hs"]) + abs(r["lam_a_red"] - r["as_"]) for r in all_rows]) / 2),
            total_mae_base=float(np.mean([abs(r["base_total_exp"] - r["act_total"]) for r in all_rows])),
            team_total_mae_base=float(np.mean([abs(r["base_team_exp"] - r["hs"]) + abs(r["base_team_exp"] - r["as_"]) for r in all_rows]) / 2)),
        ml_pass_beats_both_brier=bool(fb < bb and fb < eb),
        ml_pass_beats_both_logloss=bool(fl < bl and fl < el),
        calibration_deciles_pooled=dec)


def load_inputs(here):
    import requests
    games = json.load(open(os.path.join(here, "pitching_dataset.json")))
    teams = requests.get("https://statsapi.mlb.com/api/v1/teams?sportId=1",
                         timeout=60).json()["teams"]
    names = {t["id"]: t["name"] for t in teams}
    park = os.path.join(here, "..", "..", "data", "park_factors_2022_2024.json")
    if not os.path.exists(park):
        park = os.path.join(here, "park_factors_2022_2024.json")
    return games, park, names


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    games, park, names = load_inputs(here)
    if "--audit" in sys.argv:
        full = run(games, park, names, only_fold=2024)
        trunc = [g for g in games if g["date"] <= "2024-12-31"]
        cut = run(trunc, park, names, only_fold=2024)
        assert set(full) == set(cut), "audit: game sets differ"
        diffs = [pk for pk in full if full[pk] != cut[pk]]
        print(f"AUDIT: {len(full)} predictions for 2024 fold; "
              f"bit-identical under future-data truncation: {len(diffs) == 0} "
              f"(diffs: {len(diffs)})")
        assert not diffs
        return
    out = run(games, park, names)
    print(json.dumps(out, indent=1))
    with open(os.path.join(here, "mlb_phase_d_full_result.json"), "w") as fh:
        json.dump(out, fh, indent=1)


if __name__ == "__main__":
    main()
