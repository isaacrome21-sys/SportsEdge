# NFL discrete final-score / margin distribution v2 — pre-lock

**Status:** specification locked before any 2026 W4+ look. No scoring on this branch.
Research only. Do not edit production engines. Attempt 9 stays the live `.5` owner.

2025 discrete v1 is **FAILED and spent** (#1247). Do not retune v1. Do not reuse 2025.
Do not reuse 2026 W1–W3 (already read for Attempt 9 diagnostics).

## Why v2 exists

v1 under-massed integer 3/7 **push** on 2025 REG (4.3% pred vs 8.7% obs, n=46, 4.42 pp > 3 pp gate).
The key-lift-on-Poisson grid is the spent shape. v2 needs a different shape, not another clip on the same table.

## Locked choices (before any look)

### Fit / tune window
NFL regular season **2021, 2022, 2023, 2024** only. Finals only. No playoffs in the fit.
No market prices as features. The frozen 2021–2024 key table (`8b66310c…`) may be **inputs to shape design**, not a second 2025/2026 fit.

### Validation window (one shot)
NFL regular season **2026 weeks not yet played as of this lock, starting Week 4**.
Completed REG finals only. One look after the window is fully scored. No mid-window retune.

If v2 fails that window, the next spec needs a **new unused** window. Not a second look at 2026 W4+.

### Mean model
Frozen Attempt 9 raw margin and total stay the location. This spec only changes **shape** around those means. Do not refit Attempt 9 coefficients here.

### Shape (different from v1; not tuned on 2025 or 2026)
- Same score grid `home in 0..70`, `away in 0..70`.
- Do **not** reuse the v1 clipped key-lift Poisson as the promotion shape.
- Allowed family (choose one, freeze before the W4+ look): independent overdispersed count pair **or** a bivariate discrete with explicit extra mass on exact margins {0, ±3, ±7} fit only on 2021–2024, then renormalized. No peek at 2026.
- Push mass is the grid sum on that exact line. No ad-hoc push parameter after freeze.

### Integer 3 / 7 until the pass
Integer spreads at **3 and 7** stay **NO_MODEL** until this one-shot 2026 W4+ pass.
Same for integer totals until the same pass. Moneyline stays NO_MODEL until tie mass clears the same look.
`.5` Attempt 9 card is unchanged.

### Gates on 2026 W4+ (must all hold; one look)
1. Moneyline: |P(home win) − obs| and Brier vs coin / vs 2021–2024 home-win rate.
2. Integer spread 3 and 7: push |pred − obs| ≤ 3 pp **and** cover |gap| ≤ Attempt-9 half-point gap + 3 pp. Small-n note only; gate still binds.
3. Integer totals 40–51 when a close integer exists: same 3 pp push tolerance.
4. Key histogram 3/7/10/14: no line off by more than 5 pp with n ≥ 80.

Fail any gate → v2 fails. Do not retune on 2026 W4+.

### After a pass (separate promotion PR; not this branch)
- Integer 3/7 and integer totals become eligible.
- `.5` parity vs Attempt 9 still required.
- Label remains `NOT Model_P / NOT Truth Gate / NOT OFFICIAL` until that PR.

## Explicitly not in v2
Retuning v1. Scoring this PR. Production engine edits. Using 2025 or 2026 W1–W3 as the promotion gate. Halves, quarters, team totals, alts, props, M2 revival.
