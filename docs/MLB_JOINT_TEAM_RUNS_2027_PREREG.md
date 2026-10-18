# Pre-registration: MLB joint team-runs and pitcher H+BB+ER challengers (2027)

Registered 2026-10-13, before any evaluation. Nothing in this document has been
run against outcome data. Research only: no activation, no registry wiring, no
`eligible=true` under any result. Paid data and backfill: none.

## Windows
* Fit window (parameter freezing only): 2024–2026 MLB regular-season final
  scores from public StatsAPI already on hand. No 2026 postseason rows.
* Evaluation window: **2027 regular season, single look**, opened once after the
  regular season ends. 2024/2025/2026 are used and may not serve as holdout.
* Failed holdouts are final: no retuning and re-looking (precedent #2156 F5).

## A. Joint team runs: SHARED_PACE_NB vs INDEPENDENT_NB (production)
* Inputs: identical production means (`calibrated_full_game_means` of the frozen
  V8 30-game team means), team r = 3.1311081685642352, extras mean
  0.7541092756530898.
* Frozen before 2027: `shared_r` = MLE of the SHARED_PACE_NB likelihood of final
  (away, home) scores on the fit window, single fit, recorded with data sha256
  in a commit before 2027 Opening Day. If MLE hits the bound (shared_r > 1e4, i.e.
  no correlation), hypothesis A is withdrawn, not re-specified.
* Primary metric: mean joint-score log loss over all 2027 regular-season games
  with a pregame-captured means record (games lacking one are excluded and
  counted; never imputed).
* Secondary (reported, not decision): totals O/U Brier at the DK closing line
  (only where genuine paired DK quotes were captured pregame), push frequency
  calibration on integer totals, Brier for ML and ±1.5 run line, team-total Brier.
* Decision: challenger "passes" iff log-loss improvement > 0 with a paired game
  bootstrap (10,000 resamples, seed 20270401) 95% CI lower bound > 0, AND totals
  Brier not worse by more than 0.002. A pass only permits a further pre-registered
  forward check; it never makes any market eligible.
* Baselines: production INDEPENDENT_NB (exact analytic PMF from this module) and
  a naive league-average joint PMF (both teams at league mean).

## B. Pitcher H+BB+ER structured joint model vs production empirical sum
* Challenger: start-level latent exposure (outs recorded, NB); H | outs ~ NB(rate_h
  × outs), BB | outs ~ NB(rate_bb × outs), ER | H, BB ~ NB(a + b·(H+BB)), rates by
  empirical Bayes per pitcher from strictly-prior starts; hyperparameters frozen on
  the fit window.
* Population: 2027 regular-season starts with a verified pregame starter binding
  (`mlb_pit_binding`) and genuine paired DK H+BB+ER quotes captured pregame.
* Metric: log loss of the settled outcome at the DK line (push excluded and
  counted), vs production `pitcher_joint_engine` and vs devigged DK.
* Decision rule as in A (bootstrap seed 20270402). Postseason block unaffected.

## Not covered
Postseason, live markets, F5 (separate prereg #2156 lineage), stolen bases
(NOT_OFFERED).
