# MLB_GAME_DIST_V1 — Phase D, FULL FIDELITY (starter/bullpen decomposition implemented)

**Verdict under the design's §3.1 criteria, exactly as applied in PR #2833:
FAIL.** The full-fidelity construction beats neither naive baseline on
pooled moneyline Brier or log loss, and its totals / team-total MAE are
worse than the league-average baselines pooled and in every fold. Per
§3.1, Phase D passing is necessary to proceed to preregistration drafting.
**It does not pass. MLB_GAME_DIST_V1 does not proceed on this evidence.**

**Evidence state: DESIGN / OOS evidence only.** Nothing here is a verified
play, opens PLAY eligibility, or starts a clock. Metrics are against
outcomes only — no historical market baseline exists (Gap G4), so Phase D
could only ever be accuracy evidence. PAPER/0u throughout.

---

## What this run is

PR #2833 executed Phase D at **reduced fidelity**: PIT (opponent run
prevention) at team level only; the §2.2 starter/bullpen decomposition was
not implemented because pitching game logs had not been pulled. This run
implements the decomposition in full, on a fresh pull, and re-runs the
**same** §3.1 protocol — same folds (fit ≤2022→2023, ≤2023→2024,
≤2024→2025, ≤2025→2026), same baselines (home base rate; simple Elo;
league-average totals), same park handling, same joint negative-binomial
grid, same metrics, same pass bar. **No criterion or threshold was moved.**
A team-level-PIT replica is scored in the same pass on the identical data
snapshot, so the fidelity delta is isolated from snapshot noise.

### The decomposition as implemented (design §2.2)

For team T facing opponent O, with S = the pitcher who actually started
for O (design §2.3):

```
PIT_O = (exp_inn_S × starter_rate9_S + (9 − exp_inn_S) × bullpen_rate9_O) / 9
```

- `starter_rate9_S` — S's runs allowed per 27 outs in his strictly-prior
  **starts**, shrunk toward the fold-fit league RA9 with prior weight
  150 outs (50 IP) — the design's "shrunk by innings pitched". Starter
  history is seeded by chronological replay of the whole fit window and
  accumulates in-season; every entry is strictly prior to the game scored.
- `exp_inn_S` — S's mean innings per strictly-prior start, shrunk toward
  the fold-fit league mean starter innings with 5 pseudo-starts, clamped
  to [1.0, 8.75]. Fold-fit league mean starter innings: 5.11–5.15;
  realized mean expected innings used: 5.24–5.29 per fold.
- A starter with **< 3 prior starts** in the data window is priced at the
  unknown prior (league RA9, league mean starter innings) — never omitted,
  never at face value. Share of test games with at least one unknown-prior
  starter: 13.0% (2023) declining to 9.7% (2026) as history deepens.
- `bullpen_rate9_O` — O's bullpen runs allowed per 27 outs, expanding
  strictly-prior within the test season, prior-season final bullpen RA9
  carried in as the mix prior while O has < 20 current-season games
  (mirroring the design's OFF carry-in rule), shrinkage prior weight
  180 outs at the mix rate. Fold-fit league bullpen RA9: 4.51–4.55;
  league RA9 overall: 4.50–4.56.
- Rates are per-27-outs as the design's PIT formula states; PIT_O enters
  the same λ slot the reduced run's per-game PIT rate occupied (declared
  normalization, identical for both teams).

The shrinkage weights (150 outs / 5 starts / 180 outs) are implementation
constants declared a priori in the model file's header — the design
specifies the shrinkage structure, not these weights. **Exactly one
configuration was run. Nothing was tuned against the test folds.** A
different weighting or structure would be a new version of the
construction, not a patch to this one, and is not attempted here.

### Data

Fresh pull from the official MLB StatsAPI (public, free): schedule/results
plus boxscore pitching splits for every regular-season game 2021–2026 —
**14,577 games** (2021: 2,429 · 2022: 2,430 · 2
...[truncated 6423 chars]023: 2,430 · 2024: 2,429 ·
2025: 2,430 · 2026: 2,429), sha256
`f9c0865159e1d53b88f8a0a379d004a31f7959ab753df2390bdacc46b89846bd`
(`pitching_dataset_manifest.json`). Sanity flags over all 14,577 games:
**zero** missing boxscores, **zero** games without exactly one
games-started pitcher per team, **zero** games where summed pitcher runs
differ from the official score. Test folds total **n = 9,718** (#2833's
snapshot: 9,733; the 15-game delta is a snapshot difference in
schedule-pull dedup — the in-run replica below reproduces #2833's pooled
Brier and log loss to four decimals, so the two snapshots are
equivalent for every comparison drawn here).

## Results

### Pooled (n = 9,718) — the §3.1 verdict surface

| Metric | FULL fidelity | Reduced replica (same data) | #2833 published (reduced) | Base rate | Elo |
|---|---|---|---|---|---|
| ML Brier ↓ | **0.2567** | 0.2546 | 0.2546 | 0.2492 | 0.2487 |
| ML log loss ↓ | **0.7070** | 0.7026 | 0.7026 | 0.6916 | 0.6912* |
| Total MAE ↓ | **3.685** | 3.641 | — | 3.558 | — |
| Team-total MAE ↓ | **2.580** | 2.554 | — | 2.513 | — |

*Elo log loss 0.6912 here vs 0.6911 in #2833 (snapshot delta, immaterial).

**Pass bar:** Brier must beat base rate AND Elo — 0.2567 beats neither.
Log loss must beat both — 0.7070 beats neither. Totals MAE must beat the
league-average baseline — worse pooled and in every fold. **FAIL on every
leg.**

### Per fold — moneyline

| Fold | n | Brier full | Brier replica | Brier base | Brier Elo | LL full | LL replica | LL base | LL Elo |
|---|---|---|---|---|---|---|---|---|---|
| 2023 | 2,430 | 0.2556 | 0.2540 | 0.2498 | 0.2480 | 0.7046 | 0.7014 | 0.6927 | 0.6899 |
| 2024 | 2,429 | 0.2539 | 0.2511 | 0.2496 | 0.2484 | 0.7011 | 0.6954 | 0.6924 | 0.6904 |
| 2025 | 2,430 | 0.2575 | 0.2552 | 0.2484 | 0.2475 | 0.7086 | 0.7038 | 0.6899 | 0.6885 |
| 2026 | 2,429 | 0.2600 | 0.2582 | 0.2492 | 0.2509 | 0.7138 | 0.7100 | 0.6915 | 0.6959 |

### Per fold — totals MAE (baseline = league-average total)

| Fold | Full | Replica | Baseline |
|---|---|---|---|
| 2023 | 3.740 | 3.702 | 3.628 |
| 2024 | 3.540 | 3.494 | 3.421 |
| 2025 | 3.761 | 3.714 | 3.618 |
| 2026 | 3.698 | 3.654 | 3.566 |

### Calibration (pooled, full fidelity)

Stated mean probability spans **0.391–0.640** across deciles while the
realized home win rate stays inside **0.509–0.570** — the same signature
as the reduced run (probability spread with no corresponding outcome
spread), slightly wider.

## What the decomposition changed

It made every metric **worse**, pooled and in every fold: ΔBrier +0.0021,
Δlog loss +0.0044, Δtotal MAE +0.044, Δteam-total MAE +0.026 vs the reduced
replica on identical data. Splitting PIT into a single-starter term plus a
bullpen term injects game-to-game variance (who starts tonight) that the
outcomes do not reward at the declared shrinkage weights — the team-level
rate was already averaging over exactly that noise. The honest conclusion
is that the reduced run's failure was **not** a fidelity artifact:
MLB_GAME_DIST_V1's λ structure, at full §2.2 fidelity, does not beat
knowing the home base rate or a plain Elo on 2023–2026 walk-forward
outcomes. Re-weighting the shrinkage until the sign flips would be tuning
against the test folds; it is not done here and would in any case
constitute a new construction version requiring its own design pass.

## Lookahead audit

Point-in-time discipline is the whole game in a walk-forward; the feature
pipeline was audited four ways:

1. **Ordering + watermark assertion (in code).** Games are processed in
   (date, gamePk) order. Every history object (team OFF/PIT accumulators,
   bullpen accumulators, starter history) is updated only **after** the
   game it describes has been scored, and an assertion fires if the
   history watermark is not strictly prior to the game being scored. It
   never fired across 9,718 scored games.
2. **Truncation test (executed).** The 2024 fold was re-run on a dataset
   truncated at 2024-12-31: all **2,429** predictions are **bit-identical**
   to the full-data run (`--audit` mode). No future game can move a past
   prediction in this pipeline.
3. **Fold constants.** League level, league RA9, league bullpen RA9,
   league starter innings, home field, NB dispersion, extra-innings share,
   base rate, and Elo HFA are fitted on the fit window (seasons ≤ fit_end)
   only. Prior-season carry-ins use season test−1 finals — always inside
   the fit window. Starter history is seeded from fit-window games only,
   then accumulates strictly-prior in-season starts.
4. **Declared identity caveat.** The starter used for a game is the
   pitcher who **actually** started it (design §2.3's confirmed-starter
   definition). His identity is the only same-day input; his rate and
   expected innings come exclusively from starts completed before that
   game's date. In forward operation the identity input is the last
   confirmed probable at decision time (design §2.3); backtests cannot
   observe probables historically, and §2.3 names the actual starter as
   the confirmed starter — stated here so the substitution is on the
   record, not buried.

Self-audit note: the first full run's pooled replica row was checked
against #2833's published numbers before the full-fidelity row was
believed (Brier 0.2546 = 0.2546; log loss 0.7026 = 0.7026) — the pipeline
reproduces the prior run before it is trusted to judge the new one.

## Files

- `fetch_mlb_phase_d_full.py` — StatsAPI schedule + boxscore pull
  (resumable, per-season cache); regenerates the dataset + manifest.
- `pitching_dataset.json` / `pitching_dataset_manifest.json` — the exact
  data snapshot scored (sha256 in the manifest).
- `mlb_game_dist_v1_phase_d_full.py` — the full-fidelity Phase D
  (decomposition, replica, baselines, metrics, `--audit` mode).
- `mlb_phase_d_full_result.json` — machine-readable results.
- `REPORT.md` — this report.

Reproduce: `python3 mlb_game_dist_v1_phase_d_full.py` (writes the result
JSON), `python3 mlb_game_dist_v1_phase_d_full.py --audit` (truncation
test). Requires the repo's `data/park_factors_2022_2024.json` (sha256
`62f4ff8cd3d9…`, unchanged from #2833 — the §4-B refreshed pin remains a
freeze-time obligation, and this construction does not reach a freeze).

## Bottom line

Full fidelity does not rescue MLB_GAME_DIST_V1. Phase D fails at both
fidelities, by more at full fidelity. Under the design's own rules the
construction does not proceed to preregistration drafting, and this
report closes the fidelity question the #2833 disclosure left open.
Any successor is a new construction with its own design — it may not
inherit this one's folds as a tuning set.
