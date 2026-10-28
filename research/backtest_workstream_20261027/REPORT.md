# Backtest workstream — DESIGN-stage OOS screens, executed Oct 27, 2026 (overnight)

**Evidence state: DESIGN / OOS evidence only. Nothing in this report is a
verified play, opens PLAY eligibility, or starts a clock.** Verdicts are each
construction's own preregistered/design criteria applied exactly as written.
Mid-run owner rule change (Oct 27 ~22:53 CT) noted: the >=50 graded forward
picks gate for "verified" was abolished by the owner; verified now means
passing preregistered chronological OOS validation vs both the existing model
and a contemporaneous market baseline. That change does not alter any
construction's own screen criteria below, and no construction below meets its
criteria — so nothing here is a candidate for a verified label under either
regime. PAPER/0u throughout.

## Inventory of DESIGN-stage constructions with a specified OOS protocol

| Construction | Protocol specified | Executable tonight? | Verdict (own criteria) |
|---|---|---|---|
| NFL_ANCHORED_RATINGS_V1 (NFL sides/totals replacement) | Design §3.2 pre-freeze screens, 2020–2025 walk-forward vs nflverse close | YES — executed here | **FAIL** (both markets) |
| CFB_CONVERGED_ANCHOR_V1 (CFB sides/totals replacement) | Design §7 viability screen vs SDV closes | Already executed Oct 26 (PR #2789, merged); QB-term variant not executable (Gap G3) | **FAIL** (recorded Oct 26; not re-run) |
| NBA sides/totals successor (PR #2786) | Protocol requires preregistration BEFORE screening + timestamp-authenticated baseline | NO — Gap G2 | **NOT-EXECUTABLE** |
| MLB_GAME_DIST_V1 Phase D (MLB game lines) | Design §3.1 accuracy walk-forward vs outcomes + 2 naive baselines (no market baseline exists, Gap G4) | YES — executed here (reduced fidelity, disclosed) | **FAIL** |
| MLB batter successor (PR #2786) | Screen vs captured DK no-vig baseline on identical event/line/time pairs | NO — Gap G1 (no historical batter-prop lines exist) | **NOT-EXECUTABLE** |

---

## 1. NFL_ANCHORED_RATINGS_V1 — EXECUTED → FAILED_SCREEN (both markets)

Protocol followed exactly: design §2.2 ratings core (iterative opponent-adjusted
off/def, ridge prior P0=4 at prior-season final ratings, league level L from the
window, eligibility gate), §2.4 fitted terms (QB table bounded |δ|≤4 fitted on
design residuals; rest term clip ±1; totals-only weather terms capped |adj|≤2),
§3.1 anchoring (w=0.15, cap C=4), §2.5 σ fitted with floor 12.5, §3.2 screens
with PR #2809's band guards (bands on capped disagreement 0–1/1–2/2–3/3–4,
min n=20/band). Walk-forward by week, 2020–2025 REG, nflverse `games.csv`
(sha256 43416d3e…), baseline = nflverse closing snapshot (design baseline;
vs-close is never verified CLV).

- n = **1,517** priced games per market, seasons 2020–2025.
- Fitted constants: HFA 1.49; β_rest 0.203; QB δ home: backup-with-prior-starts
  −3.80, backup-no-prior-starts +0.53; away margin coefs +3.87 / +4.00 (cap);
  weather: wind≥15 −4.64 (fit; application capped), temp≤32 +0.80.
  σ: spread 12.69, total 13.10.
- **SPREAD:** MAE close 9.797 / raw core 10.704 / anchored 9.822 → Screen 1 FAIL
  (anchored worse than close). Realized cover by band 46.8% / 52.8% / 42.6% /
  48.3% → Screen 3 FAIL (not non-decreasing). Band 2–3 overstates stated cover
  by +8.6 pp (> 7.5) → Screen 2 FAIL. **FAILED_SCREEN on all three screens.**
- **TOTAL:** MAE close 10.298 / raw 10.966 / anchored 10.302 → Screen 1 FAIL
  (by 0.004). Realized cover 53.9% / 43.9% / 49.8% / 51.2% → Screen 3 FAIL.
  Screen 2 PASS. **FAILED_SCREEN.**
- Design-internal inconsistency flagged for the record: at w=0.15, C=4,
  σ≥12.5, the §2 probability map caps stated cover at Φ(0.6/12.5) ≈ 51.9%,
  below the §3.3 pick threshold of 0.545 — under that reading the pick rule
  could never fire even if the screens had passed. (§2.5's 62.6% remark uses
  the pre-shrink capped deviation instead.) Moot after the screen failure;
  recorded so a future version does not inherit it silently.
- Per the design, a failed screen means the construction does not advance.
  No tuning or re-run was performed.

## 2. CFB_CONVERGED_ANCHOR_V1 — ALREADY EXECUTED Oct 26 → FAIL (not re-run)

The §7-style viability screen was run Oct 26, 2026 and merged as PR #2789
(`research/cfb_successor_20261026/SCREEN_REPORT.md`): Week 5+ FBS/FBS,
n = 1,599 identical scored games per market, 2023–2025 SDV closes.
SPREAD FAIL: β +0.037 (< +0.10 required), model MAE 12.92 vs close 12.12
(worse by 0.80 > 0.5 tolerance). TOTAL FAIL: β +0.072, model MAE 13.25 vs
close 12.52 (worse by 0.73). That score-only instantiation is retired; it was
not re-run tonight. The full design's QB-continuity term remains
**NOT-EXECUTABLE**: no point-in-time pre-kickoff CFB starter designations
exist in any admitted source (Gap G3), and no retrospective QB evidence was
invented. Flat −110 ROI labels and vs-close (never verified CLV) per standing
rulings.

## 3. NBA sides/totals successor (PR #2786) — NOT-EXECUTABLE

One-line protocol/input gap: the protocol's step 1 forbids screening before a
preregistration with pinned hashes, and its baseline must be
*timestamp-authenticated* — no free source supplies per-book timestamped NBA
closes (Gap G2); the date-only SBR screens already on record were negative
(sides RMSE 13.452 vs 12.751; ML Brier 0.21755 vs 0.20670; totals RMSE 18.977
vs 18.051) and were not re-run or resurrected.

## 4. MLB_GAME_DIST_V1 Phase D — EXECUTED (reduced fidelity) → FAIL

Protocol: design §3.1 folds (fit ≤2022→2023, ≤2023→2024, ≤2024→2025,
≤2025→2026), StatsAPI schedule/results (14,601 REG games 2021–2026 pulled;
9,733 test games), strictly-prior expanding ratings with prior-season
carry-in, in-repo park factors, joint negative-binomial grid (r fitted per
fold ≈ 3.53–3.62). Metrics vs outcomes only — no market baseline exists
(Gap G4), so Phase D could only ever be accuracy evidence.

**FIDELITY DISCLOSURE:** PIT is team-level (opponent shrunk runs-allowed
rate); the §2.2 starter/bullpen decomposition was NOT implemented (starter
expected innings require pitching game logs not pulled tonight; probable
pitchers were pulled at 99.9% coverage but unused). The pass bar below is
applied to this reduced-fidelity core.

- **Moneyline, pooled (n=9,733): Brier model 0.2546 vs base-rate 0.2492 vs
  Elo 0.2487; log loss model 0.7026 vs 0.6916 vs 0.6911.** The model loses to
  BOTH baselines on BOTH metrics, in the pooled folds and in every single
  fold (per-fold table in `mlb_phase_d_result.json`).
- **Totals:** model total MAE worse than the league-average-total baseline in
  all 4 folds (3.70/3.49/3.71/3.65 vs 3.63/3.42/3.61/3.56). Team-total MAE
  likewise worse in all 4 folds.
- Calibration deciles (pooled): stated mean_p spans 0.403–0.626 while realized
  home win rate stays 0.495–0.550 — probability spread with no corresponding
  outcome spread.
- Design §3.1: Phase D passing is necessary to proceed to preregistration
  drafting. **It does not pass. MLB_GAME_DIST_V1 does not proceed on this
  evidence.** (The 2027 forward-clock plan in the design is unaffected as a
  plan, but earns nothing from Phase D.)

## 5. MLB batter successor (PR #2786) — NOT-EXECUTABLE

One-line input gap: the screen requires a captured no-vig bookmaker baseline
on identical event/line/time pairs, and no free historical batter-prop lines
exist anywhere located (Gap G1) — forward DK capture is the only path, so no
historical screen can be run.

## Method notes

- All runs executed tonight from a fresh clone of main (bc00a6106) in an
  isolated temp dir; no code was run from the quarantined workspace clone.
- A spread sign-convention bug in the first NFL run (cover definition) was
  caught by an empirical convention check against moneylines, fixed, and the
  screen re-run; only the corrected run is reported.
- Files: `nfl_anchored_ratings_v1_design_screen.py`, `nfl_screen_result.json`,
  `nfl_screen_predictions.csv`, `mlb_game_dist_v1_phase_d.py`,
  `mlb_phase_d_result.json`.
