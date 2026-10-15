# MLB Lane A Run Line ±1.5 vs Market — Chronological Evaluation Spec (M2)

- **Spec written:** 2026-10-14 (before any run-line result on this corpus
  was computed by this lane).
- **Label of any output:** RESEARCH_EVIDENCE — retrospective, development
  data. This evaluation promotes NOTHING, changes no production status,
  and does not touch Lane A activation (OFF).
- **Evidence class (verbatim, never upgraded):** the closing snapshots in
  the source corpus are UNTIMESTAMPED. Every market verdict from this
  corpus is in the **retrospective-diagnostic evidence class**. It does
  NOT satisfy the PR #2077 strict paired contract (timestamped paired
  pregame quotes) and may not be entered as strict-contract validation.
- **Question:** On development data, does the Lane A Poisson cover
  probability for the MLB run line ±1.5 beat the no-vig closing-market
  cover probability on the identical matched subset, in chronological
  walk-forward order? (M1 scored the moneyline only; the run-line leg of
  the same means has never been scored.)

## 1. Model identity (exact)

- Code: `artifacts/free_models.py` at main commit
  `2a713380c7d49733577c238a126f487382634040` (current main, 2026-10-14;
  merge of PR #2307), loaded from the evaluation worktree — never from a
  stale tree.
- Path evaluated: the Lane A (LANE_A_INDEPENDENT) construction exactly as
  in the M1 spec §1 — `context_for()` rating construction →
  `score_means()` → `model_probability("MLB", "SPREAD", "HOME",
  home_spread, home_mean, away_mean)`.
  - Constants: PRIORS["MLB"] base 4.4 runs, HFA 0.20; rating = rounded
    bounded(mean of ≤5 most recent same-season margins × 0.12, ±0.7);
    independent Poisson, support truncated at k = 38, renormalized.
  - `model_probability` returns (win, push); at a ±1.5 line push mass is
    zero by construction, so the scored model probability is `win`.
  - Owner-disabled factors (ERA pitcher adj, recent form, rest)
    contribute exactly zero on this code identity.
- **Verification precondition (must pass before any M2 number is
  reported):** the M1 evaluator (`scripts/eval_mlb_lane_a_vs_close.py`,
  copied verbatim from branch `research/mlb-lane-a-evaluation-20261013`)
  re-run against this pinned tree must reproduce M1's published results
  exactly except `generated_at` (matched n = 10,237; Brier model
  0.247856; log loss model 0.688863; ΔBrier +0.011523 [+0.007548,
  +0.016433]; ΔLogLoss +0.025641 [+0.015651, +0.038144]). This proves the
  Lane A means on this pin are the M1 means — the file changed since
  the M1 pin (655715907) only outside the Lane A path, and the
  reproduction is the proof, not the assumption.

## 2. Declared evaluation configuration

Identical to the M1 spec §2: corpus-backed provider reconstructing
`PublicContext.schedule()` semantics (same-season completed games,
strictly before the target start, identical-start games batch,
tuple-sorted descending, first 5); weather neutralized to 0.0 (the one
named non-PIT input); fixture verification replaced by the corpus
record; franchise keying by corpus `fullName` with the Athletics alias
mapping. No deviation is added for this market.

## 3. Point-in-time audit

Identical to the M1 spec §3 table. Market prices never enter the model
leg (Lane A is market-blind by construction). Final scores are used
only as outcomes after prediction and as sample inputs for strictly
later games.

## 4. Data provenance

- Corpus: ArnavSaraogi/mlb-odds-scraper dataset (SportsBookReview
  provenance), file `mlb_odds_dataset.json`, SHA-256
  `3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b`,
  80,120,813 bytes, 13,121 games, 2021-04-01 → 2025-08-16. Payload
  verification: `~/workspace/sportsedge/historical_baseline_probes/
  FINDINGS.md` §2 (2026-10-12).
- **The corpus is NOT in the repository** (verified by file listing of
  the pinned tree, 2026-10-14). It is a local-only research file; see
  `DATASET_MANIFEST.md` in this folder for the source, acquisition
  path, and hashes. Any reproduction requires acquiring the file from
  its public source and matching the SHA-256 above.
- License: none stated in the source repo; SBR terms apply. Internal
  research use only; no redistribution.
- **Exclusions (predeclared):**
  - Evaluation population: `gameType == 'R'` only (11,040 games).
  - SEALED WINDOW: games starting in [2024-07-01, 2024-09-01) UTC are
    excluded from BOTH scoring and rating samples (765 regular-season
    games).
  - Games with no final score, and tied final scores (none exist in
    this corpus), are excluded with reasons.
  - Market-availability exclusions (§5) are counted with reasons.

## 5. Market baseline (run line)

- Book selection: one book per game, fixed priority declared in
  advance: DraftKings → FanDuel → Caesars → bet365 → BetMGM →
  BetRivers NY. Only `currentLine` (the close) is used; `openingLine`
  is never mixed in.
- **Main-line rule:** a book qualifies for a game only if its
  pointspread `currentLine` has `homeSpread == -awaySpread`,
  `|homeSpread| == 1.5`, and both prices usable (numeric, non-zero,
  |price| ≥ 100). The first qualifying book in priority order supplies
  the pair. (Corpus fact recorded at spec time: exactly one pointspread
  entry exists per (game, book); most books hang ±1.5 nearly always —
  BetRivers NY usually hangs a different spread and is last in the
  chain, so it is reached only when no earlier book qualifies.)
- Exclusion reasons: `NO_POINTSPREAD_ENTRIES` (no pointspread entries
  at any book), `NO_MAIN_RUNLINE_CLOSE` (entries exist; no priority
  book hangs a usable two-sided ±1.5 close).
- Market probability: exact no-vig formula of the M1 spec §5 applied
  to the run-line prices — implied q from each American price,
  p_home_cover = q_h / (q_h + q_a), the probability the home team
  covers its −1.5/+1.5 spread.
- Owner audit fields: per accepted game the audit records both raw
  American prices, the bookmaker, the spread, and the scheduled first
  pitch. `snapshot_created_at` = **NOT_RECORDED_BY_SOURCE** and
  `minutes_snapshot_to_first_pitch` = **NOT_COMPUTABLE**, uniformly —
  never invented (corpus odds entries carry no timestamps).

## 6. Protocol

Streaming chronological walk-forward, identical to the M1 spec §6.
Model and market are scored on the IDENTICAL matched subset for this
market (population games outside the sealed window with final scores
and a usable ±1.5 closing run line per §5). Every excluded game is
listed with its reason; a missing-game bias audit compares included vs
excluded games (count by season, home-win rate). The overlap with
M1's moneyline matched subset is reported.

## 7. Metrics and the predeclared bar (market leg)

- Per-game paired Brier score and log loss (probabilities clamped at
  1e-15) of the cover event y = 1{home margin + homeSpread > 0},
  model vs market; pooled and per-season.
- Paired differences (model − market; negative = model better) with
  95% percentile CIs from a block bootstrap over ISO calendar weeks,
  2,000 resamples, seed 20261013.
- **Gate (declared before results):**
  - BEATS_MARKET iff pooled ΔBrier CI entirely < 0 AND pooled
    ΔLogLoss CI entirely < 0.
  - INCONCLUSIVE_BY_COVERAGE iff matched n < 1,000, or any full
    season (2021–2024) contributes n < 200.
  - Otherwise DOES_NOT_BEAT_MARKET (CI position reported).

## 8. Calibration leg (descriptive, not gated)

On the identical matched subset:
- Model cover-probability Brier and log loss alone; calibration in
  predicted-probability deciles (mean predicted vs realized cover
  rate).
- CRPS of the model's margin distribution (difference of the module's
  two truncated Poissons) vs the realized margin, with the expanding
  season-to-date league climatology margin distribution (strictly
  prior same-season games outside the sealed window) as a descriptive
  comparator; fixtures with < 30 prior same-season games are excluded
  from the comparator and counted.

## 9. Verification required before the verdict is reported

- **Parity:** for the first 25 scored games, the pinned `calculate()`
  driven with a SPREAD/HOME row at the selected book's spread must
  return a Lane A view whose `estimate_p` equals the pipeline `win`
  to < 1.5e-6 and whose `push_p` is 0.
- **Determinism:** a full re-run reproduces the results JSON exactly
  except `generated_at`.

## 10. What any verdict does and does not unlock

Mirrors the M1 spec §8. A pass is research evidence that Lane A's
run-line probabilities beat untimestamped SBR closing run lines on
2021–2025 development data — nothing more: no eligibility, no
strict-contract credit, no activation. A fail is research evidence
that the same Poisson means that lose the moneyline also lose (or
not) the run line, and is reported in full either way.
