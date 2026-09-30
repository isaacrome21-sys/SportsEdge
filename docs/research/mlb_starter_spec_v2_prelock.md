# Starter component v2 — pre-lock specification

**Status:** specification locked in writing. No code, fit, or evaluation on a
held-out window until this document is treated as the candidate definition.

## Failed prior attempts (do not re-use these windows for tuning)

- Existing `context_adjusted_means` starter multiplier vs defense blend on
  **2026-09-15 → 2026-09-27** (174 games): mean |gap| 2.62 vs 1.38; Brier 0.242
  vs 0.236. **FAIL.** Documented in
  `mlb_starter_vs_defense_heldout_results_20260915_27.md`.
- That window has now judged **two** starter attempts. It is **burned for
  tuning**. A later pass on Sept 15–27 alone is not promotion evidence.

## Allowed evaluation windows for v2

Pick **one** pre-registered window that does **not** include 2026-09-15..27 as
the sole decision sample:

- **Forward:** 2026-09-28 onward (regular season / early postseason — note
  postseason caution separately), or
- **Earlier regular season:** a contiguous stretch before 2026-09-15 (e.g.
  August or early September), fixed in the run receipt before numbers are read.

Sept 15–27 may appear only as a **secondary** descriptive check, never as the
promotion gate for v2.

## Production baseline (unchanged)

Defense blend only:

```
away_mean = 0.5 * away.runs_for + 0.5 * home.runs_against
home_mean = 0.5 * home.runs_for + 0.5 * away.runs_against
```

Scored with shipped Stage-1 Gamma-Poisson (`r = 5.217229403204152`).

## Diagnosed failure modes of v1 multiplier

1. **Double-counting the starter.** Team runs-allowed already embeds recent
   starter performance. Multiplying again stacks the same signal twice —
   consistent with lower mean bias but worse absolute / line error.
2. **ERA over a few starts is noise.** Prefer peripherals that stabilize with
   fewer innings: K, BB, HR allowed (rate form), with strong shrinkage to league.
3. **Starter is not the full game.** ~55–60% of outs; bullpen should remain at
   team level. Adjust only the starter share.

## v2 candidate definition (locked)

### A. Team shell (same as production)

Keep the defense-blend shell as the game-level baseline. Do **not** replace it
with offense-only or raw team averages.

### B. Residual starter effect (not a second full-game multiplier)

For the pitcher expected to start against team T:

1. Build a **stabilized starter run-prevention residual** relative to the
   **team’s recent runs-allowed mean**, not relative to league alone:
   - Use innings-weighted K%, BB%, HR% (or K-BB and HR rates) from prior starts
     strictly before the evaluation game’s date.
   - Map rates → expected runs allowed per 9 via a fixed, predeclared mapping
     (no fit on the evaluation window).
   - Residual: `starter_ra9_hat - team_runs_against_per_game_scaled_to_ra9`
     (exact scaling constants declared in implementation commit).
2. **Shrinkage:** posterior mean toward 0 residual with prior strength equivalent
   to at least ~40–60 IP (exact τ locked in implementation commit). Few-start
   pitchers barely move the mean.
3. **Innings share:** `w = clip(expected_starter_outs / 27, 0.45, 0.65)` from
   prior mean outs, default 0.55 if unknown. Only fraction `w` of the team’s
   allowed runs is shifted by the residual; `(1-w)` stays at the team shell.

Opponent scoring mean becomes:

```
shell = defense_blend component for that side
adjusted = shell * (1 + w * k * residual_scaled)
```

where `k` and residual scaling are fixed constants chosen **before** looking at
the evaluation window (implementation commit must print them and hash the
config). No grid search on the evaluation window.

### C. Explicit non-goals for v2

- No weather fit (still neutral unless PIT forecast archive exists).
- No re-tuning of full-game dispersion.
- No use of postgame starter identity; if PIT starter archive is missing, the
  run remains diagnostic and cannot promote.
- No third attempt of the **v1 multiplier** design.

## Promotion gate (unchanged)

On the **pre-registered** window only:

1. Mean absolute calibration gap on game totals 6.5 / 7.5 / 8.5 / 9.5 improves
   vs defense blend, and
2. Mean Brier on those four lines improves vs defense blend,

under the shipped Stage-1 dispersion. Both required. Secondary metrics (MAE,
mean error) are descriptive.

If either gate fails, production stays on defense blend.

## Implementation order

1. This document (done).
2. Implementation commit with frozen constants + unit tests for residual/
   shrinkage / share math only.
3. Pre-register evaluation window in a one-line receipt commit.
4. Run evaluation; publish numbers; promote only on a clear gate pass.
