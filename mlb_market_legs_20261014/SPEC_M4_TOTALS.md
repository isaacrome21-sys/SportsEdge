# MLB Lane A Total Runs vs Market — Chronological Evaluation Spec (M4)

- **Spec written:** 2026-10-14 (before any totals result on this corpus
  was computed by this lane).
- **Label of any output:** RESEARCH_EVIDENCE — retrospective, development
  data. This evaluation promotes NOTHING, changes no production status,
  and does not touch Lane A activation (OFF).
- **Evidence class (verbatim, never upgraded):** the closing snapshots in
  the source corpus are UNTIMESTAMPED. Every market verdict from this
  corpus is in the **retrospective-diagnostic evidence class**. It does
  NOT satisfy the PR #2077 strict paired contract (timestamped paired
  pregame quotes) and may not be entered as strict-contract validation.
- **Question:** On development data, does the Lane A Poisson
  probability of going over the closing total beat the no-vig
  closing-market over probability on the identical matched subset, in
  chronological walk-forward order — where each game is scored at the
  total its selected book actually closed? (The main-line totals leg
  has never been run; a recorded phase-7 harness failure at *alternate*
  total lines implicates the construction but is not this measurement.)

## 1. Model identity (exact)

- Code: `artifacts/free_models.py` at main commit
  `2a713380c7d49733577c238a126f487382634040` (current main, 2026-10-14;
  merge of PR #2307), loaded from the evaluation worktree.
- Path evaluated: the Lane A construction exactly as in the M1 spec §1
  — `context_for()` → `score_means()` → the module's own
  `model_probability("MLB", "TOTAL", side, line, home_mean,
  away_mean)`, which returns (win, push) from the joint distribution of
  the module's two independent truncated Poissons (support k = 38,
  renormalized).
- **Scored model probability (declared):** the conditional over
  probability `p_model = win_over / (win_over + win_under)`, where
  `win_over` and `win_under` are the module's win masses for sides
  OVER and UNDER at the selected book's line. Both legs of the
  comparison are conditional-on-resolution probabilities: the market
  no-vig formula (§5) is exactly this conditioning, and the module's
  own fair-price construction (`_lane_view`) uses the same
  win/(win+loss) conditioning. Push mass is reported per game, never
  silently dropped (see §5 push rule).
- Owner-disabled factors contribute exactly zero, as in M1.
- **Verification precondition:** identical to SPEC_M2 §1 — the M1
  evaluator re-run against this pin must reproduce M1's published
  results exactly except `generated_at` before any M4 number is
  reported.

## 2. Declared evaluation configuration

Identical to the M1 spec §2 (corpus provider semantics; weather
neutralized 0.0; corpus record as fixture; Athletics alias mapping).
One addition, declared: the model's predicted total distribution for
the calibration leg is the convolution of the module's two truncated
Poisson pmfs — the same joint distribution `model_probability`
integrates; no new construction is introduced.

## 3. Point-in-time audit

Identical to the M1 spec §3 table. The closing total of the selected
book is a market input to the comparison only; it never enters the
model's means (Lane A is market-blind by construction — the line
selects which event of the model's own distribution is scored, it does
not shape the distribution).

## 4. Data provenance

Identical to SPEC_M2 §4: ArnavSaraogi/mlb-odds-scraper dataset
(SportsBookReview provenance), `mlb_odds_dataset.json`, SHA-256
`3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b`,
80,120,813 bytes, 13,121 games, 2021-04-01 → 2025-08-16. **The corpus
is NOT in the repository**; see `DATASET_MANIFEST.md` in this folder.
License: none stated in the source repo; SBR terms apply; internal
research use only.
- **Exclusions (predeclared):** population `gameType == 'R'` (11,040);
  sealed window [2024-07-01, 2024-09-01) UTC excluded from scoring AND
  rating samples (765); no-final-score and tied-final exclusions with
  reasons; market-availability exclusions (§5) counted; push outcomes
  (§5) excluded from paired scoring and counted.

## 5. Market baseline (totals) and the push rule

- Book selection: one book per game, fixed priority: DraftKings →
  FanDuel → Caesars → bet365 → BetMGM → BetRivers NY. Only
  `currentLine` is used. A book qualifies if its totals `currentLine`
  carries a numeric `total` and both `overOdds`/`underOdds` usable
  (numeric, non-zero, |price| ≥ 100). The first qualifying book in
  priority order supplies the line and the pair — books hang different
  totals, and each game is scored at its selected book's line.
- Exclusion reasons: `NO_TOTALS_ENTRIES`, `NO_USABLE_CLOSING_TOTAL`.
- Market probability: exact no-vig formula of the M1 spec §5 applied
  to the over/under prices: `p_market = q_over / (q_over + q_under)`.
- **Push rule (declared before results):** the realized total T is
  compared with the selected line L. T > L → y = 1 (over); T < L →
  y = 0 (under); T == L (possible only for integer L) → the bet
  pushes: the game is EXCLUDED from the paired Brier/log-loss scoring
  and counted as `PUSH_OUTCOME_EXCLUDED`, overall and per season. Both
  scored probabilities are conditional on resolution, so a pushed
  game carries no win/loss either leg can be scored on. Push-outcome
  games remain in the calibration leg's distribution scoring (§8),
  where a realized total is a valid observation regardless of the
  line.
- Owner audit fields: as in SPEC_M2 §5 (raw prices, book, line,
  first pitch; `snapshot_created_at` = **NOT_RECORDED_BY_SOURCE**;
  `minutes_snapshot_to_first_pitch` = **NOT_COMPUTABLE**).

## 6. Protocol

Streaming chronological walk-forward, identical to the M1 spec §6.
Model and market scored on the IDENTICAL matched subset (population
games outside the sealed window, with final scores, a usable closing
total per §5, and a non-push outcome). Every excluded game listed
with its reason; missing-game bias audit as in M1; overlap with M1's
moneyline matched subset reported; the distribution of selected
closing lines reported per season.

## 7. Metrics and the predeclared bar (market leg)

- Per-game paired Brier score and log loss (clamped at 1e-15) of the
  over event, model vs market; pooled and per-season.
- Paired differences with 95% percentile CIs, block bootstrap over
  ISO calendar weeks, 2,000 resamples, seed 20261013.
- **Gate (declared before results):**
  - BEATS_MARKET iff pooled ΔBrier CI entirely < 0 AND pooled
    ΔLogLoss CI entirely < 0.
  - INCONCLUSIVE_BY_COVERAGE iff matched n < 1,000, or any full
    season (2021–2024) contributes n < 200.
  - Otherwise DOES_NOT_BEAT_MARKET (CI position reported).

## 8. Calibration leg (descriptive, not gated)

- On the paired-scoring subset: calibration deciles of the model's
  conditional over probability vs the realized over rate.
- On ALL matched games with a usable closing total (including
  push-outcome games): CRPS of the model's total-runs distribution
  (§2 convolution) vs the realized total, with the expanding
  season-to-date league climatology total distribution (strictly
  prior same-season games outside the sealed window) as a
  descriptive comparator; fixtures with < 30 prior same-season games
  are excluded from the comparator and counted. Per-season and pooled.

## 9. Verification required before the verdict is reported

- **Parity:** for the first 25 scored games, the pinned `calculate()`
  driven with a TOTAL/OVER row at the selected book's line must
  return a Lane A view whose `estimate_p` equals the pipeline
  `win_over` and whose `push_p` equals the pipeline push mass, each
  to < 1.5e-6. (The scored conditional probability is then pure
  arithmetic on the module's own outputs.)
- **Identity check:** win_over + push + win_under == 1 to < 1e-9 on
  every scored game.
- **Determinism:** a full re-run reproduces the results JSON exactly
  except `generated_at`.

## 10. What any verdict does and does not unlock

Mirrors the M1 spec §8. A pass is research evidence on development
data in the retrospective-diagnostic class only — no eligibility, no
strict-contract credit, no activation. A fail is reported in full.
