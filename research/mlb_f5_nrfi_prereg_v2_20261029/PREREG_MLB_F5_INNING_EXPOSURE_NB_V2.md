# MLB F5 inning-exposure NB, forward-market prereg v2 (DRAFT)

Version label `MLB_F5_INNING_EXPOSURE_NB_V2`. **DRAFT, NOT FROZEN.** PAPER / 0u. It incorporates `COMMON_V2_TERMS.md` (T1–T7) by reference; that file is pinned with this one at freeze.
- Predecessor: `docs/preregs/MLB_F5_INNING_EXPOSURE_NB_PREREG_20261013.md` (v1, unevaluated, kept as history).
- Change log vs v1 is in §7.

## 1. Candidate (carried from v1 §1 unchanged)
Per team-half, F5 runs = sum over innings 1–5.
- Inning mean mu_i = r_T,i * [s_i * a_S + (1 − s_i) * a_B], where:
  - s_i is the starter-still-pitching share. It is estimated from the starter's last 10 strictly-prior starts (370-day lookback, minimum 3); otherwise the league strictly-prior share by inning is used.
  - a_S is the starter runs-allowed index, Gamma-shrunk with prior weight 60 batters faced.
  - a_B is the bullpen index, prior weight 30 innings.
  - r_T,i is the batting team's strictly-prior per-inning runs (inning 1 separate; innings 2–5 pooled).
- Inning runs are NB2 with a single league dispersion k, fit by MLE on training innings only.
- Halves are independent and convolved to a joint grid 0..30.
- Starter comes from `mlb_pregame_starter_adapter` only (T6).

## 2. Data
- Free MLB StatsAPI schedule, linescore and boxscore, regular season, sportId=1.
- Training: 2021–2026 regular-season games Final strictly before 2026-10-13T00:00:00Z, which covers the full 2026 RS. The 2026 postseason is excluded.
- Every feature uses only games Final on dates strictly before the target date.
- Raw-response sha256 and fetch time are recorded per file.

## 3. Population
2027 MLB regular-season games with 5 complete innings.
- **Settlement:** the 4.5-inning "home leads" case is settled per the named book's published F5 rule for each market. That rule must be quoted verbatim in FREEZE_RECORD: **OWNER_PIN_REQUIRED** (rule text and date retrieved). Until then, v1's exclusion rule (exclude and count) stands as the default.
- Suspended or shortened games are excluded and counted.

## 4. Targets
- (a) F5 ML three-way (A/T/H). Two-way with tie push is reported separately: p_away' = P(A>H)/(1−P(tie)).
- (b) F5 total over/under 4.5 and 5.5.
- (c) Home F5 team total over 2.5.
- Integer lines carry explicit push mass.
- Market lines actually offered differ by game. Leg (b) uses, per game, the line the book quoted at close for each market type. The candidate and baseline are scored at that same line.

## 5. Legs (both must pass on every primary target; T1)
- **(a) vs existing model (T3, production m30 F5):** mean log loss per target. Passes if the 95% date-clustered CI of (candidate − m30) has upper < 0.
- **Also vs the v1 non-market baselines:** B1 league empirical and B2 scaled full-game are retained as reported diagnostics, not gating.
- **(b) vs market (T4):** for each target with a paired close, the 95% date-clustered CI of (candidate − de-vigged close) log loss must have upper < 0.
  - Target (a) uses the three-way market if the book offers it; otherwise the two-way with tie push, scored on non-tie games.
  - Which form is primary: **OWNER_PIN_REQUIRED**.
- **Secondary (reported):** Brier, calibration slope/intercept (10 bins), RPS on total runs, CLV and ROI per T4.

## 6. Verdict
Exactly one of the following, read once (T2).
- **VERIFIED:** both legs pass on all primary targets, minimum rows are met (T5), and the blocked share is <= threshold (T6).
- **FAIL:** any leg fails on any primary target with sufficient data.
- **INSUFFICIENT_DATA:** minimum rows not met, blocked share over the threshold, or no admitted market capture.
- No PLAY without alpha = 0.05/k (T1).

## 7. Changes vs v1 (memo §2 items 1–6)
1. Existing-model baseline is production m30 (v1 had none).
2. Market leg is mandatory and fully specified (v1: "MISSING" allowed).
3. Post-Oct 27 law, forward clocks non-gating, alpha 0.05/k.
4. Version label, SPEC_HASHES, FREEZE_RECORD, exact-head review, owner merge, one-look clause.
5. Starter stack precondition and blocked-rate INSUFFICIENT_DATA rule.
6. Book settlement rule pinned at freeze; bootstrap switched to date-clustered; 2026 RS explicitly training-only.
