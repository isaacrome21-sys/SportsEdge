# PREREGISTRATION — NFL Totals LEVEL Model (candidate vs the Stage 2 N3 baselines)

**Status: written and hash-locked BEFORE any candidate score was
computed.** The evaluator (`eval_nfl_totals_level_model.py`, same
directory) verifies this file's SHA-256 against `SPEC_HASHES.txt`
at load and refuses to score on a mismatch. Hash also recorded in
the lane report to the owner.

- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation on development data (2018–2025). NOT a
  market verdict, NOT validation, NOT a promotion input. No
  production model, registry, card label, or threshold changes as
  a result of this run. In particular the production totals path
  and its `WATCH_NFL_TOTAL_PRIOR_ONLY` disposition
  (`NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING`) are **not** modified
  by this work; any wiring is a separate owner-ruled step.
- **Why this exists:** Stage 2 item **N3** verdicted the shipped
  totals construction **DOES_NOT_BEAT_BASELINE** (total CRPS
  7.8225 vs league climatology 7.7126; paired Δ +0.1099
  [+0.0283, +0.1987]) because the total was never given a level
  model — its mean is a frozen 22-points-per-team prior adjusted
  only by a margin-form rating split. This preregistration tests
  exactly one hypothesis: **a point-in-time per-team scoring-rate
  level model, with no other change, beats both the frozen prior
  and league climatology on the total.**

## 1. Evaluand reuse (comparability contract)

This evaluation REUSES the Stage 2 N3 evaluation
(`mlb_market_legs_20261014/SPEC_N1_N3_NFL_CALIBRATION.md`,
SHA-256 `9e005933cda2cabfbc673140ab5093f9395d5032e3965d1037caa90e65828d60`)
verbatim wherever it defines the comparison:

- **Corpus:** nflverse `games.csv`, local copy
  `~/workspace/tmp/bt_data/nfl_games.csv`, SHA-256
  `a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284`,
  verified at load; only the Stage 2 fields are read (season,
  game_type, gameday, gametime, away_team, home_team, away_score,
  home_score). The file's line columns are never accessed.
  Corpus is NOT in the repository.
- **Population:** REG games, seasons 2018–2025, final scores
  present (expected n = 2,127). Games sharing an identical
  kickoff instant are batch-processed (neither sees the other in
  any sample or pool).
- **Paired subset:** fixtures with ≥ 30 strictly-prior same-season
  games (Stage 2 climatology eligibility; expected n = 1,887).
  All paired gates are decided on this subset. Model-only scores
  are also reported on the full population.
- **Scoring machinery:** total CRPS — closed-form Normal CRPS for
  Normal candidates/baselines, integer-support empirical CRPS
  (the Stage 2 `crps_empirical_int` construction) for
  climatology. Paired per-game differences; 95% percentile CIs by
  block bootstrap over ISO calendar weeks, 2,000 resamples, seed
  20261015 — the Stage 2 algorithm, copied with attribution.
- **Reproduction precondition:** before any candidate verdict is
  reported, this evaluator must reproduce Stage 2's frozen-prior
  and B2 numbers on the paired subset (frozen mean total CRPS
  7.8225, B2 mean 7.7126, paired Δ +0.1099, CI [+0.0283, +0.1987],
  each to within 1e-3; means expected to 1e-6). If reproduction
  fails, the run stops and reports the discrepancy instead of a
  verdict.

## 2. Baselines (verbatim Stage 2 set)

- **FROZEN PRIOR (as shipped):** `artifacts/free_models.py` at
  current main `0f96676f` — blob
  `253b0c6d91840c906941216be117f2acc1497a57`, byte-identical to the
  Stage 2 pin (verified at load). Construction: team rating =
  round(bounded(mean of ≤ 5 most recent same-season prior margins
  × 0.12, −3, +3), 3); home_mean = 22 + 0.75 + home_rating;
  away_mean = 22 − 0.75 + away_rating; total ~
  Normal(home_mean + away_mean, 13.5). Injury points 0.0 and
  weather adjustment 0.0 (Stage 2 declared neutralizations).
- **B2 — league total climatology:** empirical distribution of
  game totals over strictly-prior same-season games (expanding),
  scored by empirical CRPS. Identical to Stage 2.

## 3. The candidate — LEVEL model (the only new construction)

For a fixture (away A @ home H, kickoff t, season S), using ONLY
completed games strictly before t (batch rule above):

- **Trailing samples:** each team's ALL completed same-season
  games before t (not a last-5 window — level estimation uses the
  full trailing sample; the last-5 window is the frozen prior's
  margin-form construction, not this model's). Per-season team
  abbreviation keying is exact (Stage 2 §2).
- **League rate:** L = total points scored / total team-games over
  all strictly-prior same-season games (expanding, batch rule).
  If the pool is empty (season opener), L = 22.0 (the production
  base), declared.
- **Shrunk team rates** (shrinkage constant **κ = 4.0 games**,
  fixed here):
  - off_T = (PF_T + κ·L) / (n_T + κ) — points scored per game,
  - def_T = (PA_T + κ·L) / (n_T + κ) — points allowed per game,
  where PF_T / PA_T / n_T are T's trailing same-season totals
  (n_T = 0 ⇒ the rate is L exactly).
- **Expected team scores** (additive-average form: the expected
  score of T against O is the average of T's offensive rate and
  O's defensive rate — it equals L when both are league-average,
  and stays inside [min, max] of its two inputs; the
  multiplicative ratio form is NOT used):
  - E_home = (off_H + def_A) / 2 + 0.75
  - E_away = (off_A + def_H) / 2 − 0.75
  (0.75 = half the production HFA of 1.5, matching the frozen
  prior's ±0.75 split.)
- **Predicted quantity:** home score ~ Normal(E_home, σ_team) and
  away score ~ Normal(E_away, σ_team), independent, so the priced
  distribution is **total ~ Normal(E_home + E_away, 13.5)**.
  The total sd is FIXED at the production 13.5, deliberately:
  this evaluation isolates the LEVEL effect. A fitted sd would
  confound level-vs-variance attribution (§6 diagnostics exist
  precisely to measure the variance side without letting it into
  the candidate).
- **Declared non-features:** no pace/plays adjustment — the corpus
  carries no play-volume fields, so per-game rates absorb average
  pace; named here as a limitation and a future hypothesis, not
  silently dropped. No injuries/weather (no PIT source; Stage 2
  neutralizations stand). No market data of any kind. No margin
  rating (the candidate's total mean comes ONLY from the level
  construction — blending in the frozen prior's rating would
  confound the comparison this run exists to make).

## 4. Metrics and gate

- **Primary metric:** total-distribution CRPS on the paired
  subset, computed per §1.
- **Adoption gate (both legs required):** the candidate
  BEATS_BASELINE iff the pooled paired ΔCRPS 95% CI is entirely
  < 0 against the FROZEN PRIOR **and** entirely < 0 against B2
  CLIMATOLOGY. Any other outcome is DOES_NOT_BEAT_BASELINE, with
  the failing leg(s) named.
- **Secondary (descriptive, no gate):** Brier score of the OVER
  event at the fixed half-line grid
  {37.5, 40.5, 43.5, 46.5, 49.5, 52.5} for candidate, frozen
  prior, and B2 (empirical tail), on the paired subset.
- **Per-season reporting:** paired ΔCRPS vs both baselines for
  each season 2018–2025, with CIs. Descriptive (the gate is
  pooled), but any season in which the candidate loses to a
  baseline is named in the report, not averaged away.
- **Determinism:** a full re-run reproduces the results JSON
  exactly except `generated_at`.

## 5. Point-in-time audit

| Input | PIT status |
|---|---|
| Trailing PF/PA samples | Strictly prior same-season games only; batch rule at identical kickoffs |
| League rate L | Expanding, strictly prior, same batch rule |
| Injury / weather | Neutralized 0.0 (declared, §2) — no retrospective data |
| Market prices | Never enter |
| Outcomes | Realized scores, used only after prediction |

## 6. Error decomposition (reported whatever the verdict)

So a negative verdict still produces the next hypothesis, the
evaluator reports, on the paired subset (candidate vs actuals):

- **Level:** mean signed error of the candidate total mean;
  pooled and per-season (a level model that cannot track a
  season's scoring level repeats the frozen prior's 2020 failure
  in miniature).
- **Variance:** sd of (actual total − candidate mean) vs the
  fixed 13.5; plus a DIAGNOSTIC-ONLY CRPS of the candidate means
  under a per-season refit sd (never the candidate, never gated)
  — the size of the remaining gap that variance alone explains.
- **Team-split:** mean absolute error of E_home and E_away
  separately, and the correlation of the two team errors
  (split errors cancel in the total only if independent or
  negatively correlated; positive correlation is a totals cost).

## 7. What the verdict does and does not unlock

A pass produces exactly one thing: a wiring PROPOSAL to the owner
(research-labeled totals pricing path), written in the report. It
does not wire anything, change any card label, or promote the
model. A fail is reported in full with §6's decomposition and the
largest error component named as the next hypothesis. Neither
outcome touches the G2 program or any sealed attempt.
