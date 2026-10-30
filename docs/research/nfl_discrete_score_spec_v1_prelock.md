# NFL discrete final-score / margin distribution v1 — pre-lock

**Status:** specification locked. No scoring on this branch. Research only.
Not a model-surface promotion. Attempt 9 stays the live `.5` owner.

## Why one spec unlocks three markets

Attempt 9 and M2 both fail closed on integer lines because they have no
validated mass at exact margins. On DraftKings a tie refunds, so moneyline is
`P(margin > 0)` vs `P(margin < 0)` with push at 0. Integer spreads at 3 and 7
are the same object: mass at that exact margin. Integer totals are mass at that
exact combined score. One discrete joint distribution of `(home_score, away_score)`
prices all three without a separate ML model.

Halves and quarters are **out of scope**. They need period paths on top of this.

## Locked choices (before any look)

### Fit window
NFL regular season **2021, 2022, 2023, 2024**. Finals only. No playoffs in the fit.
No market prices as features.

### Validation window (one shot)
NFL regular season **2025**. Unused for this spec. If v1 fails 2025, v2 needs a
new unused window — not a second look at 2025, and not 2026 W1–W3 (already
read for Attempt 9 diagnostics).

### Mean model
Frozen Attempt 9 raw margin and total stay the location. This spec only adds
**shape**: a discrete distribution around those two means. Do not refit Attempt 9
coefficients here.

### Shape (first principles, not tuned on 2025)
- Build a score grid `home in 0..70`, `away in 0..70`, integers.
- Start from independent Skellam / Poisson-with-overdispersion around the two
  team means implied by Attempt 9 `(total ± margin) / 2`, then apply a **fixed**
  key-number lift at margin ∈ {±3, ±7, ±10, ±14} using the 2021–2024 empirical
  frequency ratio vs a no-key Poisson, clipped so the four keys are not fit to
  2025.
- The 2021–2024 key-frequency table is computed once, hashed, and frozen before
  the 2025 look.
- Push mass at margin = 0 and at integer totals is the grid sum on that line.
  No ad-hoc push parameter.

### Gates on 2025 (must all hold)
Report at posted close lines from nflverse (settle only):
1. Moneyline: Brier and calibration of `P(home win)` excluding ties. Not worse
   than Attempt 9’s half-point home-cover Brier on the same games where both exist.
2. Integer spread 3 and 7 (home handicap ±3, ±7): mean |predicted cover − observed|
   across those lines ≤ the Attempt 9 half-point cover gap plus 3 pp, and push
   rate |pred − obs| ≤ 3 pp.
3. Integer totals 40 through 51: mean |gap| across those lines, and push rate
   at the integer. Same 3 pp push tolerance.
4. Key-number histogram: predicted vs observed mass at 3/7/10/14. No line may
   be off by more than 5 pp with n ≥ 80.

If any gate fails, v1 fails. Do not retune keys on 2025.

### Card rules after a pass (separate promotion PR)
- Moneyline, integer spread, integer total become eligible.
- `.5` markets must stay within ~1 pt of current Attempt 9 model_p (parity test).
- Dual clock for any moneyline evidence bound to the old surface.
- Label remains `NOT Model_P / NOT Truth Gate / NOT OFFICIAL` until that PR.

## Explicitly not in v1
QB / injury / weather / rest as model inputs.
Team totals, halves, quarters, alts, props.
M2 revival.
Using 2026 W1–W3 as the promotion gate.
