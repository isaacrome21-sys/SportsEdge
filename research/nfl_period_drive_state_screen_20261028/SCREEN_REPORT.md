# NFL_PERIOD_DRIVE_STATE_V2 — design screen report

**Verdict: SCREEN_PASS (DESIGN_PASS) — every design §5 leg passes under
both pre-declared seeds.** Construction `NFL_PERIOD_DRIVE_STATE_V2`,
screened exactly as designed in
`research/successor_designs_20261028/DESIGN_NFL_PERIOD_DRIVE_STATE_V2.md`
(PR #2872). Run 2026-10-28, results of record:
`screen_results_v2.json` in this directory (generated
2026-10-28T14:51:21Z). Inputs: `INPUT_PINS.md`. Implementation +
readings (RD-1…RD-11) + build notes: `screen_nfl_period_drive_state_v2.py`
module header.

Scope honesty, up front: this is a **design screen on seen seasons**
(2023–2025 are DESIGN data). A pass is an entry ticket only — it is
not validation, not a freeze, and not PLAY eligibility. Per design
§8, the family stays **DESIGN ONLY** (config
`sportsedge/forward_validation/configs/nfl_period_lines.json` remains
`model_version: "UNPINNED"`, counted rows zero) until a forward-prereg
revision names this construction and the owner records a freeze.
Margins are thin and are reported as-is below: the pooled margin
over B0 is 0.022 MAE (≈0.5%) and leg L2 passes exactly at its
4-of-6 minimum.

## Panel and reproduction guards (re-run, not assumed)

- Panel: 1,632 team-games (816 games, 2023–2025 REG), the
  predecessor's panel rebuilt by the v1 pack's own machinery.
- Panel integrity: 97.0% of team-games match the final score
  exactly; 3.0% differ only by overtime scoring; 0 negative
  differences; 0 NaNs; 0 unexplained.
- Baseline reproduction: this pack's B0/B1 frames reproduce the
  v1 screen's bucket MAEs with max difference **0.000000** on both
  arms — the baselines are the v1 screen's own arithmetic.
- Sibling reproduction: pooled MAE of the frozen
  `NFL_TEAM_TOTAL_DIST_V1` means = **7.7491** (screen of record:
  7.749); pooled CV c = 0.46439.

## Per-leg verdicts (design §5)

Both seeds: seed A = 20261028, seed B = 20261029; R = 10,000
replications per game; period scores are replication means.

| Leg | Criterion | Seed A | Seed B |
|---|---|---|---|
| L1 | Pooled MAE(M) < MAE(B0) **and** < MAE(B1) | **PASS** — 4.4007 < 4.4228 (B0), < 4.4695 (B1) | **PASS** — 4.4007 < 4.4228, < 4.4695 |
| L2 | M beats B0 in ≥ 4 of 6 buckets | **PASS** — exactly 4 (Q3, Q4, 1H, 2H) | **PASS** — exactly 4 (Q3, Q4, 1H, 2H) |
| L3 | Q4 leg: MAE(M) < MAE(B0) in Q4 | **PASS** — 4.2324 < 4.2573 | **PASS** — 4.2320 < 4.2573 |
| L4 | Stability: no season's pooled MAE(M) worse than B0 by > 0.25 | **PASS** — excess −0.017 / −0.008 / −0.041 (M better every season) | **PASS** — excess −0.016 / −0.010 / −0.040 |

No seed flip: the verdict does not depend on the seed (seed-to-seed
pooled MAE(M) difference ≈ 0.000002). **SCREEN_PASS.**

## MAE by bucket × arm

Seed A (seed B within ±0.002 on every M cell):

| Bucket | M (v2 sim) | B0 (league shares) | B1 (flat split) | v1 candidate (record) |
|---|---|---|---|---|
| Q1 | 3.5293 | **3.5189** | 3.6720 | 3.517 |
| Q2 | 4.2637 | **4.2460** | 4.2790 | 4.261 |
| Q3 | **3.6029** | 3.6363 | 3.7274 | 3.635 |
| Q4 | **4.2324** | 4.2573 | 4.2691 | 4.314 |
| 1H | **5.3956** | 5.4390 | 5.4232 | 5.450 |
| 2H (diagnostic) | **5.3801** | 5.4394 | 5.4459 | 5.489 |
| **Pooled** | **4.4007** | 4.4228 | 4.4695 | 4.4444 |

M beats B1 in all six buckets and B0 in four. Where M wins is the
second half — Q3, Q4, 2H — exactly the state-driven region the v1
diagnosis named; where it loses (Q1, Q2) the margins are small
(+0.010, +0.018). Against the v1 candidate's pooled 4.4444, the
drive-state construction improves every second-half bucket.

Per-season pooled MAE (seed A; seed B materially identical):

| Season | M | B0 | B1 |
|---|---|---|---|
| 2023 | 4.3538 | 4.3708 | 4.4228 |
| 2024 | 4.4552 | 4.4636 | 4.5173 |
| 2025 | 4.3930 | 4.4340 | 4.4682 |

## Q4 state-conditional breakdown (reporting only, design §5)

MAE of Q4 points by realized margin entering Q4, in §3.2
differential buckets (team's view; seed A):

| Bucket (margin entering Q4) | n | M | B0 |
|---|---|---|---|
| 0 (≤ −17) | 173 | **4.8752** | 4.8864 |
| 1 (−16…−9) | 222 | 4.6931 | **4.6080** |
| 2 (−8…−3) | 329 | 4.2512 | **4.2048** |
| 3 (−2…+2) | 184 | 4.2265 | **4.1774** |
| 4 (+3…+8) | 329 | **3.7688** | 3.8246 |
| 5 (+9…+16) | 222 | **4.4459** | 4.4668 |
| 6 (≥ +17) | 173 | **3.5769** | 3.9167 |

M's Q4 edge concentrates where game state binds hardest: teams
leading big entering Q4 (bucket 6, −0.340) and leading small
(bucket 4, −0.056), plus the deep-trailing bucket 0. It gives back
smaller amounts in the trailing-small and close buckets.

## Coherence diagnostic vs the frozen sibling (reported, never an input)

Simulated full-game team means vs the frozen
`NFL_TEAM_TOTAL_DIST_V1` means over the 1,632 team-games:
mean(sim − sibling) = **−1.69 points**; MAE(sim vs sibling) = 2.54;
correlation 0.808. The level gap is the same shortfall the
base-rate diagnostic shows (below): the simulator's level runs
≈1.7 points low against both the training record and the sibling,
while its quarter *distribution* still beats the share baselines —
B0 inherits the sibling's level, so M wins on shape despite the
level deficit. No coherence adjustment was applied anywhere;
the sibling means are not an input to the construction (§3.3).

## Base-rate build diagnostic (disclosed limitation)

Bands fixed in code before the diagnostic ran (points ±1.0, plays
±3.0, TD share ±0.02, punt share ±0.03), league-average bundles on
each fit's own training window:

| Fit | Real pts | Sim pts | Points | Plays | TD share | Punt share | Accepted |
|---|---|---|---|---|---|---|---|
| for 2023 (train 2022) | 21.88 | 21.06 | ✓ (gap 0.82) | ✓ | ✓ | ✓ | **Yes** |
| for 2024 (train 2022–23) | 21.83 | 20.61 | **✗ (gap 1.22)** | ✓ | ✓ | ✓ | **No — points only** |
| for 2025 (train 2022–24) | 22.19 | 20.95 | **✗ (gap 1.23)** | ✓ | ✓ | ✓ | **No — points only** |

The chain produces ~2.5 fewer scrimmage plays per team-game than
the training record at similar drive counts — slightly shorter
drives. The design fixes no diagnostic threshold and no
level-correction channel, and adding one after seeing build
diagnostics would be an undeclared construction change, so the
screen ran on the construction exactly as designed with this
shortfall disclosed (decision recorded in the implementation
header). The diagnostic is **not** reported as passed for the
2024/2025 fits.

## State-function stability diagnostic (design §9; reporting only)

Pass probability in key state cells, from single-season fits
(no numeric threshold is fixed by the design, so none is applied):

| Cell | 2023 fit | 2024 fit | 2025 fit |
|---|---|---|---|
| Q4 ≤2:00, trail big | 0.639 | 0.625 | 0.596 |
| Q4 ≤2:00, trail small | 0.897 | 0.833 | 0.842 |
| Q4 ≤2:00, close | 0.555 | 0.574 | 0.600 |
| Q4 ≤2:00, lead small | 0.084 | 0.107 | 0.099 |
| Q4 ≤2:00, lead big | 0.071 | 0.023 | 0.044 |
| Q4 ≤5:00, trail small | 0.695 | 0.703 | 0.728 |
| Q3, close | 0.558 | 0.519 | 0.532 |
| 1H, close | 0.563 | 0.548 | 0.548 |

The ordering (trail ≫ close ≫ lead) and rough magnitudes are
consistent across the three seasons; no design-stage falsification
is claimed and no per-season patch was made.

## Simulation diagnostics

- Unfinished replications: 0 (all games, both seeds).
- Safeties: 366,527 (seed A) / 368,147 (seed B) total safety
  events across 816 games × 10,000 replications = **0.045 per
  simulated game**. (The `safeties_per_game` field in
  `screen_results_v2.json` divides total events by games without
  dividing out replications and reads 449.2 — a mislabeled
  aggregate in the run record; the per-game rate is 0.045.)
- Training safety rate (plays starting inside the offense's own
  5): 0.0241, averaged over the three eval-season fits.

## Build notes (all before any screen statistic was computed)

- **FG-FIX:** `fg_prob` originally keyed its distance lookup on
  multiples of 5 while the fitted curve is keyed on
  [18+5k, 23+5k) buckets, silently returning the pooled make rate
  for nearly every attempt — contradicting reading RD-9. Fixed to
  the fitted edges; diagnostics re-run after the fix (points gaps
  narrowed from 1.35/1.42 to 1.22/1.23).
- **OPT:** vectorized hot paths + optional multiprocessing across
  games. No fitted value, seed, replication count, bucket,
  reading, or criterion changed; per-game streams derive from
  `SeedSequence([seed, game index])`, so results are identical
  for any worker count (this run used 2 workers).
- Tests: `tests/test_nfl_period_drive_state_v2.py` — 8 tests
  (bucket boundaries, quarter boundaries, simulator determinism
  and seed separation, point-in-time sample discipline, screen-leg
  arithmetic, panel integrity), all passing on the run tree.
- The frozen sibling (`sportsedge/nfl_team_total_dist.py`,
  `sportsedge/nfl_team_total_runner.py`, configs, prereg, pins)
  is untouched: this branch's diff against its base adds only
  this pack's files and the test file.

## What remains before any counted row (design §8, unchanged)

1. A revision of `PREREG_NFL_PERIOD_LINES_FORWARD_V1_DRAFT.md`
   naming `NFL_PERIOD_DRIVE_STATE_V2` with sha256 pins (design,
   engine, constants incl. §3.2 state functions and seed).
2. Capture expansion + intake-grammar extension for period lines
   (open preconditions).
3. Independent review (CLEARED) of the frozen revision; bootstrap
   seed and k list recorded at freeze.
4. The freeze itself is the owner's act, naming the first counted
   slate. Until then every forward row is refused fail-closed.
