# Starter component v2 — pre-lock specification

**Status:** specification locked in writing. No code, fit, or evaluation on a
held-out window until this document is treated as the candidate definition.

## Pre-score unit correction — 2026-09-29

Before the one-shot August window was scored, review found a unit mismatch in
the pre-locked FIP-style coefficients. The implementation stores K / BB / HR
rates **per out**, while standard FIP weights are expressed per inning:

```
(13 * HR + 3 * BB - 2 * K) / IP
```

Since `1 IP = 3 outs`, the equivalent weights for rates stored per out are:

```
HR = 39
BB = 9
K  = 6
```

The original pre-lock values `HR=15`, `BB=12`, `K=9` were therefore a unit
error, not fitted parameters. They are superseded **before any August score was
computed**. This amendment is a first-principles unit correction, not tuning on
the held-out set. All other constants, windows, identity policy, gate criteria,
and the 4.50 league RA9 proxy remain unchanged.

Corrected constants receipt:

`constants_sha256 = 1b1b9ed6900654e69c23b5daaf9729d85bdfec4ffa72bc921498737e2ec9c065`

## Failed prior attempts (do not re-use these windows for tuning)

- Existing `context_adjusted_means` starter multiplier vs defense blend on
  **2026-09-15 → 2026-09-27** (174 games): mean |gap| 2.62 vs 1.38; Brier 0.242
  vs 0.236. **FAIL.** Documented in
  `mlb_starter_vs_defense_heldout_results_20260915_27.md`.
- That window has now judged **two** starter attempts. It is **burned for
  tuning**. A later pass on Sept 15–27 alone is not promotion evidence.

## Pre-registered evaluation window for v2

**Primary gate (locked): 2026-08-01 → 2026-08-31** (full August regular season).

Nobody has tuned a starter candidate on this stretch. It is large enough to
judge means and line calibration.

### Explicitly off-limits for the v2 promotion gate

| Window | Why barred |
|---|---|
| 2026-09-01 → 2026-09-14 | Full-game dispersion `r` was **fit** here (#1236 / #1238) |
| 2026-09-15 → 2026-09-27 | Burned by two prior starter attempts |
| 2026-09-28 onward | Regular season is over; only a few playoff games — not enough n |

Sept 15–27 (and optionally Sept 1–14) may appear only as **secondary**
descriptive checks after the August gate is scored. They never decide promotion.

Playoff games are out of scope for v2 promotion; treat postseason totals as
small leans until a separate postseason window exists.

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

## Starter identity decision (locked before numbers)

### Archive reality

- A **pregame** starter archive **does** exist: workflow
  `mlb-pit-lineup-starter-archive.yml` (every 15 minutes, March–October) writes
  to the `data` branch.
- **Coverage starts 2026-09-13.** There are **no** August snapshots. Actual
  starters are the only option for the August gate.
- Historical StatsAPI schedule probable-pitcher fields are not a substitute for
  those snapshots; they resolve toward who started.

### Decision for v2 August gate

Use **actual starters** as a stand-in for the pregame announced starter.

- Pregame scratches / late changes are a few percent of games; the bias is
  accepted and disclosed.
- Every evaluation receipt must set
  `starter_identity_source = ACTUAL_STARTER_STAND_IN_NO_PREGAME_PIT_ARCHIVE`
  and `starter_identity_pit_verified = false`.
- This **does not** block the August promotion gate for v2. A pass is
  **provisional**.

### Path from provisional → full authority

The forward archive is already running. Clean pregame confirmation cannot use
Sept 13–27 for the promotion decision (barred windows). Full authority waits on
**playoff and/or next-season** PIT-bound evidence that the same residual effect
holds, or on explicit ops acceptance of the stand-in bias.

Weather remains neutral (no PIT forecast archive).

Deciding identity policy after reading August numbers is forbidden.

## Constants: source of `k` and residual scaling (locked before numbers)

No free parameters are fit on August or on Sept 2026.

| Symbol | Value | Source |
|---|---:|---|
| League RA9 proxy | 4.50 | **Assumed**, not measured. First-principles ~4.5 runs/team-game scale for residual units. June–July is used only for league *rate* averages (K/BB/HR per out), not for this proxy. Measuring RPG from June–July would change a frozen constant; v2 keeps 4.50 explicitly as an assumption. |
| Residual scale | residual / 4.50 | First principles: convert RA9 residual to fractional game effect |
| `k` | 1.0 | First principles: residual already in run units; no extra gain |
| Shrinkage prior τ (IP) | 50.0 | First principles: mid of the 40–60 IP band declared earlier |
| Default innings share `w` | 0.55 | First principles: ~5 IP starter |
| `w` clip | [0.45, 0.65] | First principles |

**Rate → RA9 mapping (fixed, not fit; unit-corrected before August scoring):**

```
starter_ra9_hat = 4.50
    +  9.0 * (BB_rate - league_BB_rate)
    -  6.0 * (K_rate  - league_K_rate)
    + 39.0 * (HR_rate - league_HR_rate)
```

These are the standard FIP event weights converted from per-inning form to the
per-out rates used by the implementation. League rates are computed from
**2026-06-01 → 2026-07-31** starter innings only (named fit window for league
averages — not for `k` and not for the 4.50 RA9 proxy). June–July must not
include August games.

If implementation needs any additional constant, it must be added to this table
in a commit **before** the August run. Silent defaults are not allowed.

## v2 candidate definition (locked)

### A. Team shell (same as production)

Keep the defense-blend shell as the game-level baseline. Do **not** replace it
with offense-only or raw team averages.

### B. Residual starter effect (not a second full-game multiplier)

For the pitcher who **actually started** (stand-in identity above) against team T:

1. Innings-weighted K / BB / HR rates from prior starts strictly before the
   evaluation game’s date → `starter_ra9_hat` via the fixed mapping above.
2. Residual vs team: `starter_ra9_hat - team_runs_against_mean_as_ra9`
   (team RA scaled with the same 4.50 league proxy).
3. Shrink residual toward 0 with τ = 50 IP effective prior.
4. `w = clip(mean_prior_outs / 27, 0.45, 0.65)` (default 0.55).

Opponent scoring mean:

```
shell = defense_blend component for that side
fractional = (shrunk_residual / 4.50) * k   # k = 1.0
adjusted = shell * (1 + w * fractional)
adjusted = max(0.05, adjusted)
```

### C. Explicit non-goals for v2

- No weather fit.
- No re-tuning of full-game dispersion.
- No third attempt of the **v1 multiplier** design.
- No fitting of `k` or FIP-style coefficients on August or September 2026.

## Promotion gate

On **2026-08-01 → 2026-08-31** only:

1. Mean absolute calibration gap on game totals 6.5 / 7.5 / 8.5 / 9.5 improves
   vs defense blend, and
2. Mean Brier on those four lines improves vs defense blend,

under the shipped Stage-1 dispersion. Both required. Secondary metrics (MAE,
mean error) are descriptive.

If either gate fails, production stays on defense blend.

A gate pass is **provisional production authority**. Full authority waits on
PIT-bound confirmation from the running archive outside barred windows
(playoffs / next season) or explicit ops acceptance of the stand-in.

### One-shot rule

**August is scored once.** Publish the v2 numbers; if the gate fails, v2 is
dead. A tweaked v3 does **not** get a second look at August — it needs a new,
unused pre-registered window. Re-running August after changing constants is
tuning on the test set.

## Implementation order

1. This document (done): August pre-registered, one-shot, identity decision,
   archive coverage noted, constant sources closed, FIP unit correction recorded,
   4.50 assumed not measured.
2. Implementation commit with the table above hashed + unit tests for residual /
   shrinkage / share math only.
3. Run evaluation on August **once**; publish numbers; promote only on a clear
   gate pass under the identity caveat.
