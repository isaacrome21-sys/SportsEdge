# EITHER_PITCHER shrunk-marginals prereg — Amendment 1 (written BEFORE any 2026 score)

**Prereg:** `PREREG_EITHER_PITCHER_SHRUNK_MARGINALS.md`, SHA-256
`1cc6c4eb302b708fe6aa3df184abf62efea08d968b4857cd27aa6f31a0a78dae`
(locked at `fb89b5ae`). That file is unchanged. This amendment is a
separate public record.

**When:** Sat 2026-10-17. No CHALLENGER, B1⊗B1 or B2⊗B2 score, and no
FROZEN score on 2026, existed on any data when this was written. The only
computation run so far is the §7 FROZEN-arm reproduction on 2024–25
design data, which is described below.

## 1. Data acquisition identity (§3)

Run `39026089063` of `mlb-statsapi-history`, staging branch
`data-staging/mlb-statsapi-history`, provenance
`ACQUIRED_POSTHOC_FROM_PUBLIC_STATSAPI`. Bundle SHA-256s:

| Season | pitching_gamelogs | schedule | players |
|---|---|---|---|
| 2024 | `2c18b6cf…12d1` | `031bd385…3311` | `b13bd4e3…d951` |
| 2025 | `fc5da2e8…f179` | `d0ff241e…1d74` | `653e15f5…2ea` |
| 2026 | `88a0c104…8171` | `7fbd9842…49d6` | `7d779b8c…9b63` |

Manifest status in that run: 2025 COMPLETE. 2024 and 2026 were INCOMPLETE
only because of one **Cancelled** game each (2024 HOU@CLE 746577, 2026
BAL@NYY 823490). StatsAPI marks those `abstractGameState=Final`, but they
were never played. The completeness rule was fixed to exclude Cancelled
games (`1a75eb98`). With that fix, every played game in all three seasons
has exactly two starters.

## 2. Deviation: §7 FROZEN-arm reproduction scope (2024 only, exact)

§7 asked the FROZEN arm to reproduce M31's per-cell `mean_predicted` on
2024–25 to < 1e-9.

- **2024 — reproduced exactly.** M31's own pool and pairing code was run
  on these bundles with the frozen engine blob `00cba6f6…` (branch
  `research/mlb-market-legs-20261014`). It gives the same population as
  M31: 4,858 candidate starts, 1,976 fixtures, exclusions
  SEALED_WINDOW 1,564 / POOL_LT_5 1,318, and 765 pairs. All 24
  (stat, form, rung) cells match M31's published 2024 per-season mean
  signed error to **max |Δ| = 0.0**. Identical signed error on identical
  pairs means the predictions match.
- **2025 — cannot match cell by cell, for a known reason.** M31's local
  cache held 4,846 regular-season 2025 starts. The complete record has
  **4,860** (2 × 2,430 games). M31's pitcher universe missed 14 starts,
  so M31 scored 1,395 pairs where the complete data gives 1,404. M31
  published only pooled per-cell means and has no per-pair records, so
  the 2025 difference cannot be removed or reconciled cell by cell.
- **Disposition:** the FROZEN-arm identity requirement is satisfied by
  the exact 2024 reproduction, which uses the same code, engine blob and
  rules. 2025 is reported descriptively (§5, design data only), with the
  population difference stated. **2026 scoring uses the complete data and
  the same verified code path.** No gate, threshold, constant or arm
  definition changes.

## 3. Nothing else changes

K = 10, the rung grid, the arms, the metric, seed 20261017, the gate
(including tail materiality), the 2026 test split, the ER caveat, the
market-leg exclusion, and the research-only status are all as locked in
the prereg.
