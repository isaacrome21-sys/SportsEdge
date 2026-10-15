# MLB Lane A Team Total Runs vs Realized Team Runs — Calibration Spec (M6)

- **Spec written:** 2026-10-15 (before any team-total score was computed
  by this lane). Stage 2 of the MLB market-leg lane; Stage 1 discipline
  applies throughout.
- **Label of any output:** RESEARCH_EVIDENCE — retrospective,
  development data. This is a **calibration leg only**. The market leg
  of this family is **FORWARD_ONLY_BY_DESIGN**: no historical
  team-total lines exist in any in-repo corpus, and none are scored
  here. This evaluation promotes NOTHING and changes no model,
  registry entry, or threshold.
- **Question:** On the identical matched subset scored by M1/M2/M4,
  do Lane A's team means — read as the construction's own
  independent-Poisson team-run distributions — beat the expanding
  league team-run climatology on CRPS against realized team runs?

## 1. Model identity (exact)

- Code: `artifacts/free_models.py` at main commit
  `83e0c396a4761ea3de80583be5e61e8ca2e07f9a` (current main at Stage 2
  start, 2026-10-15). The file's blob at this pin is
  `253b0c6d91840c906941216be117f2acc1497a57` — **identical** to its
  blob at the Stage 1 pin `2a713380c` and the M1 pin lineage, so the
  Lane A construction scored here is byte-identical to the one M1,
  M2 and M4 scored.
- Evaluand: per game, the team-run distributions Poisson(home_mean)
  and Poisson(away_mean) using the module's own `poisson()` (support
  truncated at k = 38, renormalized) — exactly the marginals of the
  Lane A independent-Poisson joint that M1/M2/M4 scored.
- Means provenance (hash chain, not re-derivation): the means are
  read from the Stage 1 published audit artifact
  `mlb_market_legs_20261014/audit_m2_runline.csv` (on
  `research/mlb-market-legs-20261014`), SHA-256
  `b0b39ab2a92e2114ed4ecaa9b0823396fb28bbd917d248e8cf448b82967b39dc`.
  That audit's means are the M1-verified walk-forward means (Stage 1
  §0: the M1 evaluator re-run on the pin reproduced M1 exactly). The
  evaluator verifies this SHA-256 at load and refuses a mismatched
  file. Weather neutralized and owner-disabled factors zero, exactly
  as in the audit's construction.

## 2. Population

- The identical matched subset to M1/M2/M4: audit rows with
  status INCLUDED, n = 10,237 (2021: 2,190; 2022: 2,344; 2023: 2,389;
  2024: 1,622; 2025: 1,692). Team totals need no market line of their
  own; the subset is inherited for exact comparability with the
  three market legs, and that inheritance is declared here rather
  than silently widening or narrowing the population.
- Paired-comparator subset: audit rows whose `crps_clim` field is
  non-empty (n = 10,092) — the same climatology-eligibility set as
  the M2/M4 CAL legs (fixtures with < 30 prior same-season games are
  ineligible for the expanding climatology and were counted there).
  Model-only CRPS is reported on all 10,237; every gated comparison
  uses the paired subset.

## 3. Point-in-time audit

Identical to the M1/M2 specs: the means are strictly-prior
walk-forward outputs; realized team runs enter only as outcomes
after prediction; the climatology is expanding and strictly prior
(same-season games outside the sealed window [2024-07-01,
2024-09-01), the M2 §8 construction). No market price enters this
leg at any point.

## 4. Metrics and the predeclared bar (calibration leg)

- Per team-game: CRPS of Poisson(team_mean) against realized team
  runs, computed from the module's truncated PMF by the standard
  sum over k of (F(k) − 1{y ≤ k})².
- Baseline **B1 — league team-run climatology:** the empirical
  distribution of team runs (each prior game contributes two
  team-game observations) over strictly prior same-season games
  outside the sealed window, recomputed from the corpus scores by
  the evaluator on the M2 §8 eligibility rule.
- Per-game paired statistic: mean of the two team CRPS differences
  (model − B1). Pooled and per-season paired ΔCRPS with 95%
  percentile CIs, block bootstrap over ISO calendar weeks, 2,000
  resamples, seed 20261015.
- **Gate (declared before results):** BEATS_BASELINE iff the pooled
  paired ΔCRPS CI is entirely < 0. Otherwise
  DOES_NOT_BEAT_BASELINE, CI position reported. Per-season CIs are
  reported in full and are descriptive.
- Descriptive (not gated): per-team (home/away) CRPS splits; mean
  predicted vs mean realized runs per team; PIT-histogram summary of
  the pooled team-run distributions.

## 5. Verification required before the verdict is reported

- **Artifact identity:** audit CSV SHA-256 verified at load (§1).
- **PMF hygiene:** each Poisson PMF conserves mass to 1e-12 after
  the module's own renormalization; CRPS of a point-mass check case
  reproduced by hand on one fixture.
- **Determinism:** a full re-run reproduces the results JSON exactly
  except `generated_at`.

## 6. What any verdict does and does not unlock

A pass is calibration evidence that Lane A's team means carry
team-scoring signal beyond the league's own run distribution on
2021–2025 development data — nothing more: no market verdict exists
for this family, no eligibility changes, no activation input. A
fail extends the M1/M2/M4 pattern to the team-total readout and is
reported in full either way.
