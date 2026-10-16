# REPORT — NFL Totals LEVEL Model Evaluation

**Date:** 2026-10-16 · **Label:** RESEARCH_EVIDENCE — retrospective
calibration on 2018–2025 development data. NOT a market verdict,
NOT validation, NOT a promotion input. Nothing is wired; the
production totals path keeps `WATCH_NFL_TOTAL_PRIOR_ONLY`
(`NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING`) unchanged.

**Preregistration:** `PREREG_NFL_TOTALS_LEVEL_MODEL.md`, SHA-256
`de83468b10508f601050670a0f7294e73222fea33a305e1dbe296f1cb0e2b5a4`,
written and hash-locked before any candidate score existed; the
evaluator verifies the lock at load.

## VERDICT: DOES_NOT_BEAT_BASELINE

The preregistered gate required the pooled paired ΔCRPS CI to be
entirely below zero against **both** baselines. Both legs fail
(paired subset n = 1,887, identical to Stage 2):

| Scorer | Mean total CRPS |
|---|---|
| **B2 — league total climatology** | **7.7126** |
| Candidate — LEVEL model | 7.7606 |
| FROZEN prior (as shipped) | 7.8225 |

- Candidate vs FROZEN: Δ **−0.0619** [−0.1497, **+0.0235**] —
  point estimate better, CI crosses zero → leg fails.
- Candidate vs B2: Δ **+0.0479** [−0.0345, +0.1336] —
  point estimate *worse* than the league's raw total history →
  leg fails.

Secondary (descriptive): Brier on OVER at the fixed band grid
{37.5…52.5} separates nobody — candidate, frozen, and B2 sit
within ~0.001 of each other at every line.

## Verification before the verdict

- **Reproduction precondition PASSED:** this evaluator re-derived
  Stage 2's frozen (7.82248 vs published 7.8225) and B2 (7.71262
  vs 7.7126) means and the paired Δ +0.10986 [+0.02830, +0.19868]
  vs published +0.1099 [+0.0283, +0.1987] — the comparison frame
  is Stage 2's, bit-for-bit in every digit that matters.
- Population reconciles: 2,127 scored / 240 ineligible /
  1,887 paired, exactly Stage 2's counts.
- Determinism: two full runs reproduce the results JSON exactly
  except `generated_at`.
- All hashes verified at load: prereg, Stage 2 spec reference
  (`9e005933…`), dataset (`a484c6ae…`), frozen-prior blob
  (`253b0c6d…`, byte-identical to the Stage 2 pin at current main).

## Per-season (paired ΔCRPS; negative = candidate better)

| Season | n | vs FROZEN | vs B2 |
|---|---|---|---|
| 2018 | 226 | −0.2532 [−0.5445, +0.0066] | −0.1374 [−0.3987, +0.1517] |
| 2019 | 226 | −0.2170 [−0.3992, −0.0099] | −0.1001 [−0.3317, +0.1464] |
| 2020 | 226 | **−0.4948 [−0.7646, −0.2363]** | +0.0931 [−0.1761, +0.3544] |
| 2021 | 242 | +0.0912 [−0.1853, +0.3373] | +0.0608 [−0.1873, +0.2859] |
| 2022 | 241 | +0.1465 [−0.0890, +0.3688] | +0.1492 [−0.0927, +0.3913] |
| 2023 | 242 | **+0.2696 [+0.0771, +0.4687]** | **+0.3233 [+0.0764, +0.6006]** |
| 2024 | 242 | −0.0582 [−0.2478, +0.1215] | +0.0376 [−0.1526, +0.2414] |
| 2025 | 242 | −0.0301 [−0.1830, +0.1110] | −0.0616 [−0.2117, +0.0925] |

The honest shape: the level model **fixed the frozen prior's
signature failure** — in 2020, the season that sank the prior
(Stage 2 Δ +0.5879), the candidate beats the prior decisively
(CI entirely < 0). It then gives it back: 2021–2023 trend the
wrong way, and 2023 is a significant loss against *both*
baselines (CIs entirely > 0). Early-season strength, late-sample
decay — the trailing estimate itself is the story (§ below).

## Error decomposition (prereg §6) — the largest component is LEVEL tracking

- **Level (dominant):** pooled mean signed error +0.69 points,
  but the pooled figure hides the mechanism — per-season bias
  swings from **−2.13 (2020)** to **+2.62 (2022)** and **+2.67
  (2023)**. The candidate's level is a trailing same-season
  average: it lags level *shifts* in both directions (chasing
  the 2020 jump from below; holding 2022's level into 2023's
  league-wide scoring drop). Bias variance across seasons is an
  order of magnitude larger than anything the other components
  offer.
- **Variance (negligible):** residual sd 13.77 vs the fixed 13.5;
  the diagnostic-only per-season refit-sd CRPS gains are
  ≤ 0.006 per season (and negative in 2018). No attainable sd
  choice closes a 0.048 gap to B2.
- **Team-split (nil):** home/away MAE 7.84 / 7.74; team-error
  correlation **−0.002** — split errors already cancel in the
  total; nothing to recover there.

**Next hypothesis (named, per the fail protocol):** the binding
constraint is *how fast the level estimate moves*, not its form.
A successor candidate should test recency weighting (exponential
decay on trailing games) and/or cross-season carryover with decay
(the current model restarts each season and spends its first
weeks re-learning the level) — under a NEW preregistration, with
the same baselines and gate. Separately, B2's residual edge may
partly be *shape*: an empirical distribution carries the total's
multimodality (key-number mass) that no Normal at any mean can;
a shape-aware successor (e.g., empirical residuals around the
level mean) is the second hypothesis in line. Neither is tested
here; both are recorded so the next prereg starts from evidence.

## What this changes

Nothing in production. The `WATCH_NFL_TOTAL_PRIOR_ONLY`
disposition stands — this run produced no construction that earns
a wiring proposal under the preregistered gate. The branch
carries the candidate module, evaluator, preregistration,
results, per-game audit, and tests for the record and for the
successor preregistration to build on.
