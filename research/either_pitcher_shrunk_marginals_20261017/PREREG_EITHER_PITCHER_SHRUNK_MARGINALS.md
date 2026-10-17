# PREREGISTRATION — EITHER_PITCHER from league-shrunk marginals (M31 repair)

**Status: written and hash-locked BEFORE any score of this construction
exists on any data.** No evaluator exists at lock time. The evaluator,
when built, must verify this file's SHA-256 against `SPEC_HASHES.txt` and
refuse to score on a mismatch.

- **Written:** Sat 2026-10-17 (CT), by Claude under DIRECTIONS_FOR_CLAUDE
  §5.1.3 ("repair the marginal calibration at the far rungs, prove the
  repair on held data under a new preregistration").
- **Families:** EITHER_PITCHER_HITS_ALLOWED, EITHER_PITCHER_BB,
  EITHER_PITCHER_ER.
- **Label of any output:** RESEARCH_EVIDENCE, calibration only. NOT a
  market verdict, NOT validation, NOT a promotion input. The gate
  `EITHER_PITCHER_MARGINAL_TAIL_ERROR` stays in place regardless of the
  result. Lifting it is a separate ruling by Isaac.

## 0. The measured defect (M31, `research/mlb-market-legs-20261014`)

M31 measured dependence at ≈ 0 (residual ρ: HA −0.006, BB +0.009,
ER +0.001; n = 2,160 pairs, 2024–25). The independence product is
therefore not the problem; the marginals are. The error is systematic
and has a known mechanism:

- `sportsedge/mlb_empirical_bayes.py` applies a Jeffreys Dirichlet
  prior of 0.5 per settlement category with effective n ≤ 12.
- A pitcher with **zero** exceedances in 12 starts is priced at
  0.5 / 13 = **3.85%** per side, so ≈ 7.5% "either".
- Realized at BB 6+: either rate 0.88% against the engine's 5.86%
  (error +4.98 pp [+4.55, +5.43]).
- The same shrink-toward-½ pulls the low-count rungs the other way: BB
  2-or-fewer is predicted at 0.888 against 0.941 realized.

The fix is a better per-pitcher marginal, not a dependence model. The
designated successor marginal already exists: the pitcher undercard
shrinkage challenger (PREREG_PITCHER_UNDERCARD, PR #2368, K = 10 toward
the league distribution). That challenger was ADOPT-CANDIDATE for HA and
BB and KEEP FROZEN for ER on its own single-pitcher test.

## 1. Construction under test (every constant fixed here)

For a game with starters p_A and p_B, stat m ∈ {HA, BB, ER}, and date d:

- **Marginal (per starter):** P_i(v) = (count_pool_i(v) + K·L_m(d)(v)) /
  (n_i + K), with **K = 10**, exactly the PREREG_PITCHER_UNDERCARD §3
  construction. The pool is all of the starter's prior same-season
  starts (gamesStarted = 1, strictly prior dates, no 12-start cap).
  L_m(d) is the pooled empirical distribution over all starters' prior
  same-season starts. **No re-tuning of K, here or later.**
- **Either event at rung X+:** 1 − (1 − S_A(X))(1 − S_B(X)), where
  S_i(X) = Σ_{v ≥ X} P_i(v) (independence; justified by M31's measured
  ρ ≈ 0).
- **Either event at N-or-fewer:** 1 − (1 − F_A(N))(1 − F_B(N)), where
  F_i(N) = Σ_{v ≤ N} P_i(v).
- **Rung grid:** identical to SPEC_M31 §1. HA X+ ∈ {5…10}, or-fewer
  {2…5}; BB X+ ∈ {3…6}, or-fewer {0, 1, 2}; ER X+ ∈ {3…6}, or-fewer
  {0, 1, 2}.

## 2. Arms (identical pair population)

1. **FROZEN** — production `price_pitcher_market` either branch, raw
   pools only (the M31 construction, engine blob pinned at evaluation).
2. **CHALLENGER** — §1.
3. **B1⊗B1** — each starter's raw uncapped prior pool distribution
   (K → 0), combined by the same §1 independence rule.
4. **B2⊗B2** — league distribution L_m(d) for both starters, same rule.

## 3. Data and split

- **Test population:** 2026 MLB regular-season games in which both
  starters satisfy the pool contract (≥ 5 prior same-season starts).
  Pairing is by StatsAPI `game_pk`, with M31's exclusion vocabulary
  (`PAIR_SIDE_MISSING`, `PAIR_ANOMALY`), counted.
- **Overlap, stated plainly:** the single-pitcher marginals were scored
  on 2026 starts under PREREG_PITCHER_UNDERCARD, with K fixed in advance
  and not tuned. The pair-level either events have never been scored on
  2026 by any construction. 2026 is admissible here **only because
  nothing in §1 was chosen after seeing 2026**. If Isaac rules that
  overlap disqualifies 2026, the test moves to the 2027 regular season
  unchanged (forward), and nothing else changes.
- **Design data, not scored for the verdict:** 2024–25 (M31). It may be
  used only for the §5 descriptive comparison.
- **Source:** MLB StatsAPI public endpoints (pitching gameLogs,
  schedule), acquired by GitHub Actions or the program's existing cache
  lineage. The acquisition identity (combined SHA-256 of payloads) is
  recorded before scoring. No paid source.

## 4. Metric and gate

- **Primary:** per-rung Brier of the either event, pooled over all
  (stat, form, rung) cells of a stat, paired per game-cell. 95% CIs by
  block bootstrap over ISO calendar weeks, 2,000 resamples, seed
  20261017.
- **Gate (per stat; HA, BB, ER verdicted separately):** CALIBRATION_PASS
  iff both hold:
  1. The pooled paired ΔBrier CI (CHALLENGER − arm) is entirely < 0 vs
     FROZEN **and** vs B1⊗B1 **and** vs B2⊗B2.
  2. **Tail materiality** (M31's reading rule, now a gate): no X+ cell
     has a signed calibration-error CI with lower bound > +2 pp
     (the overstatement of the buyable side that M31 measured).
- Otherwise the verdict is DOES_NOT_BEAT_BASELINE (or
  MATERIAL_TAIL_OVERSTATEMENT for a condition-2 failure), with the
  failing leg or cell named.
- **ER caveat, declared now:** the ER single-pitcher challenger tied B2
  on its own test. An ER fail here is the expected outcome, not a
  surprise. It stays reported.

## 5. Descriptive (no gate)

- Per-cell mean predicted vs realized with CIs, side by side with M31's
  FROZEN numbers.
- The same arms on 2024–25 (design data), labeled DESIGN.
- Reliability deciles at the BB 3+ / HA 7+ rungs.

## 6. Market leg — not in this preregistration

DK either-pitcher ladders are one-sided (X+). Under the paired-price law
they cannot be de-vigged. A CALIBRATION_PASS here makes the family
eligible only to be *written into* a forward market protocol: single-side
NO_DEVIG EV against the quoted price, scored prospectively under its own
preregistration through the milestone gate (`MILESTONE_SINGLE_SIDE_
REQUIRES_VALIDATED_MODEL`). PLAY remains unavailable until that protocol
passes and Isaac certifies.

## 7. Verification before any verdict is reported

- Pool parity: ≥ 25 sampled (pitcher, date) pools equal the production
  `MLBPitcherPublicSource.prior_starts` semantics (uncapped variant).
- Event-semantics hand check on ≥ 10 pairs: either probability
  recomputed by code that does not import the evaluator, < 1e-9.
- FROZEN-arm reproduction: on the 2024–25 design pairs, the evaluator's
  FROZEN arm reproduces M31's published per-cell `mean_predicted` to
  < 1e-9 before any 2026 score is computed. On failure the run stops.
- Determinism; and an independent verifier re-runs from a fresh
  worktree of the pushed head.
