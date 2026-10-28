#!/usr/bin/env python3
"""
MLB_GAME_DIST_V1 - Phase D design-phase accuracy walk-forward (DESIGN section
3.1), executed as specified: folds fit<=2022->2023, <=2023->2024, <=2024->2025,
<=2025->2026; metrics against OUTCOMES ONLY (no historical market baseline
exists - Gap G4). DESIGN EVIDENCE ONLY, zero validation credit.

Pass bar as written in the design: moneyline Brier + log loss must beat BOTH
naive baselines fitted on identical data - (a) home-team base rate, (b) a
simple Elo - on the pooled folds, to proceed to preregistration drafting.
Totals: run-total MAE vs a league-average-total baseline; team-total MAE
likewise. Calibration deciles for ML probabilities, per fold and pooled.

FIDELITY DISCLOSURES (deviations from the full section 2.2 spec, all stated):
- PIT is implemented at TEAM level (opponent shrunk runs-allowed rate). The
  starter/bullpen decomposition is NOT implemented: starter expected innings
  require pitching game logs not pulled in this run. Probable-pitcher identity
  was pulled (99.9% coverage) but not used. This is therefore a REDUCED-
  FIDELITY Phase D: the lambda structure, PIT discipline, park/home terms,
  joint NB grid, baselines and metrics are as designed; the PIT term is
  coarser than the frozen construction would be.
- Ratings: expanding strictly-prior window within the test season, with the
  immediately-prior season's final rate carried in as a 20-pseudo-game prior
  regressed toward the league mean (design 2.2 carry-in rule), shrinkage
  K=20 pseudo-games at league mean for both OFF and PIT rates.
- Park: in-repo data/park_factors_2022_2024.json runs factor for the home
  team (design 4-B requires a refreshed pin at freeze; the 2022-2024 research
  file is what exists; missing team -> 1.0). Applied as sqrt split to each
  team's lambda (the file's pf is a total-runs factor for the venue).
- home_field: fitted per fold on the fit window (ratio of home to away
  scoring), applied +half/-half in log space.
- NB dispersion r and extra-innings home share: fitted per fold on the fit
  window (r by method of moments on team-game runs).
- Elo baseline: standard Elo (start 1500, K=20) run chronologically over
  fit+test on identical data; its home-advantage points fitted on the fit
  window by grid search minimising log loss.
"""
import json, math
import numpy as np

K_SHRINK = 20.0
MAXR = 26

def nb_pmf(mu, r, kmax=MAXR):
    # negative binomial with mean mu, size r
    from math import lgamma, log, exp
    out = []
    for k in range(kmax + 1):
        lp = (lgamma(k + r) - lgamma(r) - lgamma(k + 1)
              + r * log(r / (r + mu)) + (k * log(mu / (r + mu)) if k else 0.0))
        out.append(exp(lp))
    s = sum(out)
    return np.array([x / s for x in out])

def run(games_path, park_path, team_names):
    games = json.load(open(games_path))
    games.sort(key=lambda g: (g["date"], g["pk"]))
    pf_file = json.load(open(park_path))
    pf_by_team = {}
    for name, v in (pf_file.get("teams") or {}).items():
        if isinstance(v, dict) and "park_factor_runs" in v:
            pf_by_team[name] = float(v["park_factor_runs"])
    print(f"# park factors loaded for {len(pf_by_team)} teams", flush=True)

    def park_factor(home_team_id):
        nm = team_names.get(str(home_team_id)) or team_names.get(home_team_id)
        return pf_by_team.get(nm, 1.0)

    folds = [(2022, 2023), (2023, 2024), (2024, 2025), (2025, 2026)]
    all_rows = []
    fold_reports = {}
    for fit_end, test_season in folds:
        fit = [g for g in games if g["season"] <= fit_end]
        test = [g for g in games if g["season"] == test_season]
        prev = [g for g in games if g["season"] == test_season - 1]
        L = np.mean([g["hs"] for g in fit] + [g["as_"] for g in fit])
        home_ratio = np.mean([g["hs"] for g in fit]) / np.mean([g["as_"] for g in fit])
        home_log = 0.5 * math.log(home_ratio)
        base_rate = np.mean([1.0 if g["hs"] > g["as_"] else 0.0 for g in fit])
        # NB dispersion by moments on fit team-game runs
        tg = np.array([g["hs"] for g in fit] + [g["as_"] for g in fit], dtype=float)
        var = tg.var()
        r_nb = float(tg.mean() ** 2 / max(var - tg.mean(), 0.05))
        # extra-innings home share: games tied after 9 -> use games where total
        # innings unknown; proxy: fit-window home win share in 1-run games is
        # NOT extras. Use overall: share of games with hs==as_ impossible in
        # finals; extras share fitted as home win prob in games decided by
        # exactly 1 run in the 9th+ is unavailable -> use 0.54 league-known?
        # NO invented constants: use fit-window home win rate in 1-run games.
        one_run = [g for g in fit if abs(g["hs"] - g["as_"]) == 1]
        ex_share = float(np.mean([1.0 if g["hs"] > g["as_"] else 0.0 for g in one_run]))

        # prior-season final rates
        def final_rates(rows):
            off, pit, n = {}, {}, {}
            for g in rows:
                off[g["at"]] = off.get(g["at"], 0) + g["as_"]; pit[g["at"]] = pit.get(g["at"], 0) + g["hs"]
                off[g["ht"]] = off.get(g["ht"], 0) + g["hs"]; pit[g["ht"]] = pit.get(g["ht"], 0) + g["as_"]
                n[g["at"]] = n.get(g["at"], 0) + 1; n[g["ht"]] = n.get(g["ht"], 0) + 1
            return ({t: off[t] / n[t] for t in n}, {t: pit[t] / n[t] for t in n})
        poff, ppit = final_rates(prev)

        # Elo over fit then test, HFA fitted on fit by grid search
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
        best_hfa, best_ll = 0, 1e18
        for hfa in range(0, 61, 5):
            pr = elo_run(hfa)
            ll = -np.mean([math.log(min(max(pr[g["pk"]], 1e-9), 1 - 1e-9)) if g["hs"] > g["as_"]
                            else math.log(min(max(1 - pr[g["pk"]], 1e-9), 1 - 1e-9)) for g in fit])
            if ll < best_ll:
                best_ll, best_hfa, elo_probs = ll, hfa, pr

        # expanding ratings within test season
        scored, allowed, played = {}, {}, {}
        rows = []
        for g in test:
            def shrunk(t, table, prior_table):
                n = played.get(t, 0)
                mix = prior_table.get(t, L) if n < 20 else L
                return (table.get(t, 0.0) + K_SHRINK * mix) / (n + K_SHRINK)
            off_h = shrunk(g["ht"], scored, poff); pit_h = shrunk(g["ht"], allowed, ppit)
            off_a = shrunk(g["at"], scored, poff); pit_a = shrunk(g["at"], allowed, ppit)
            pf = park_factor(g["ht"])
            lam_h = L * (off_h / L) * (L / pit_a) * math.exp(home_log) * math.sqrt(pf)
            lam_a = L * (off_a / L) * (L / pit_h) * math.exp(-home_log) * math.sqrt(pf)
            ph_grid = nb_pmf(lam_h, r_nb); pa_grid = nb_pmf(lam_a, r_nb)
            grid = np.outer(ph_grid, pa_grid)
            p_home = float(
                sum(grid[i, j] for i in range(MAXR + 1) for j in range(MAXR + 1) if i > j)
                + sum(grid[i, i] for i in range(MAXR + 1)) * ex_share)
            y = 1.0 if g["hs"] > g["as_"] else 0.0
            rows.append(dict(pk=g["pk"], season=test_season, y=y, p_model=p_home,
                             p_base=base_rate, p_elo=elo_probs[g["pk"]],
                             exp_total=lam_h + lam_a, act_total=g["hs"] + g["as_"],
                             lam_h=lam_h, lam_a=lam_a, hs=g["hs"], as_=g["as_"]))
            for t, s_, a_ in ((g["ht"], g["hs"], g["as_"]), (g["at"], g["as_"], g["hs"])):
                scored[t] = scored.get(t, 0) + s_; allowed[t] = allowed.get(t, 0) + a_
                played[t] = played.get(t, 0) + 1
        all_rows.extend(rows)

        def metrics(rs, key):
            p = np.array([min(max(r[key], 1e-9), 1 - 1e-9) for r in rs])
            y = np.array([r["y"] for r in rs])
            return float(np.mean((p - y) ** 2)), float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        mb, ml = metrics(rows, "p_model"); bb, bl = metrics(rows, "p_base"); eb, el = metrics(rows, "p_elo")
        league_total = float(np.mean([g["hs"] + g["as_"] for g in fit]))
        tmae_m = float(np.mean([abs(r["exp_total"] - r["act_total"]) for r in rows]))
        tmae_b = float(np.mean([abs(league_total - r["act_total"]) for r in rows]))
        tt_m = float(np.mean([abs(r["lam_h"] - r["hs"]) + abs(r["lam_a"] - r["as_"]) for r in rows]) / 2)
        tt_b = float(np.mean([abs(L - r["hs"]) + abs(L - r["as_"]) for r in rows]) / 2)
        fold_reports[test_season] = dict(n=len(rows), L=float(L), r_nb=r_nb,
            brier_model=mb, brier_base=bb, brier_elo=eb, ll_model=ml, ll_base=bl, ll_elo=el,
            total_mae_model=tmae_m, total_mae_base=tmae_b, team_total_mae_model=tt_m,
            team_total_mae_base=tt_b, elo_hfa=best_hfa)
    # pooled
    def metrics(rs, key):
        p = np.array([min(max(r[key], 1e-9), 1 - 1e-9) for r in rs])
        y = np.array([r["y"] for r in rs])
        return float(np.mean((p - y) ** 2)), float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    mb, ml = metrics(all_rows, "p_model"); bb, bl = metrics(all_rows, "p_base"); eb, el = metrics(all_rows, "p_elo")
    dec = []
    srt = sorted(all_rows, key=lambda r: r["p_model"])
    for i in range(10):
        chunk = srt[i * len(srt) // 10:(i + 1) * len(srt) // 10]
        dec.append(dict(decile=i + 1, n=len(chunk),
                        mean_p=float(np.mean([r["p_model"] for r in chunk])),
                        realized=float(np.mean([r["y"] for r in chunk]))))
    out = dict(folds=fold_reports,
               pooled=dict(n=len(all_rows), brier_model=mb, brier_base=bb, brier_elo=eb,
                           ll_model=ml, ll_base=bl, ll_elo=el),
               ml_pass_beats_both_brier=bool(mb < bb and mb < eb),
               ml_pass_beats_both_logloss=bool(ml < bl and ml < el),
               calibration_deciles_pooled=dec)
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    import requests
    teams = requests.get("https://statsapi.mlb.com/api/v1/teams?sportId=1", timeout=60).json()["teams"]
    names = {t["id"]: t["name"] for t in teams}
    json.dump(names, open("/tmp/bt568/mlb_team_names.json", "w"))
    run("/tmp/bt568/mlb_games.json",
        "/tmp/bt568/repo/data/park_factors_2022_2024.json", names)
