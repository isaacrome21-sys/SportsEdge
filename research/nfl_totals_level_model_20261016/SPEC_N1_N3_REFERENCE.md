# SPEC — NFL Moneyline / Spread / Total Calibration Legs (N1–N3)

Families: NFL Moneyline (N1), NFL Spread (N2), NFL Total (N3) —
**calibration legs only.** The market legs are
**FORWARD_ONLY_BY_DESIGN**: no historical paired NFL odds corpus
exists in-repo under the project's paired contract, and none is
scored here. (The schedule file used below carries single-source
line columns; they are **not used** — the classification is a
property of the evidence standard, not of what a CSV happens to
contain.)

- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation. NOT a market verdict, NOT validation,
  NOT a promotion input. No model, registry, or threshold change.
- **Written:** 2026-10-15, before any NFL score was computed.
  Stage 2 of the MLB market-leg lane; the M1/M2 spec-first
  discipline applies (corpus-backed provider, verification
  precondition, identical matched subsets per item).

## 1. Model identity (exact)

- Code: `artifacts/free_models.py` at main
  `83e0c396a4761ea3de80583be5e61e8ca2e07f9a` (blob
  `253b0c6d91840c906941216be117f2acc1497a57`, identical to the
  Stage 1 pin — SPEC_M6 §1). Evaluand: the **Lane A view** of
  `calculate()` for NFL rows, which the verification precondition
  (§6) proves equal to the direct construction below.
- Construction (from the pinned code): PRIORS["NFL"] = base 22.0
  points per team, total sd 13.5, margin sd 13.7, HFA 1.5. Team
  rating = round(bounded(mean of the ≤ 5 most recent same-season
  prior margins × 0.12, −3, +3), 3) (`context_for`; empty sample →
  rating 0.0, the production HISTORY_MISSING behavior). Means
  (`score_means`): home_mean = 22 + 0.75 + home_rating,
  away_mean = 22 − 0.75 + away_rating (injury and weather terms
  per §2). Distributions (`model_probability`, non-MLB branch):
  margin ~ Normal(home_mean − away_mean, 13.7); total ~
  Normal(home_mean + away_mean, 13.5).
- **The N3 caveat, verbatim from the engine itself**
  (`calculate()`): NFL totals carry status
  `WATCH_NFL_TOTAL_PRIOR_ONLY`, reason
  `NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING:22_PTS_PER_TEAM_PLUS_MARGIN_FORM_ONLY`.
  The total mean is a 22-points-per-team prior adjusted only by the
  margin-form rating split — there is no absolute scoring-rate
  model. The N3 run measures that gap against realized totals; it
  does not excuse it, and the results record carries this caveat
  wherever the N3 number appears.

## 2. Declared evaluation configuration

- **Corpus-backed provider** reconstructing the production
  provider's semantics over the schedule corpus (§4), exactly as
  the M1 spec did for MLB: `fixture` = the corpus game itself;
  `identify` = corpus team key; `schedule` = the production rule
  (same-season completed games strictly before kickoff, sorted
  descending, first 5; season of a Jan/Feb kickoff is the preceding
  fall's, per the pinned code).
- **Team identity:** samples are same-season only, so keying by the
  corpus's per-season team abbreviation is exact (franchise
  relocations never occur mid-season; cross-season identity is
  never consulted). Declared here so the choice is on record.
- **Injury points: 0.0 for every team** (declared evaluation
  configuration). No PIT injury source for 2018–2025 exists in the
  project's evidence base; the rating construction — the evaluand —
  is unaffected in form. This parallels M1's weather
  neutralization: `weather_total_adj` = 0.0 (no PIT forecast
  exists). Both are named here, before results, as the two
  non-PIT context inputs set to their neutral values.
- Games sharing an identical kickoff instant are batch-processed:
  neither sees the other in its sample (the M1 rule).

## 3. Point-in-time audit

| Input | PIT status |
|---|---|
| Rating samples | Strictly prior same-season games only (production `schedule` rule) |
| Injury / weather context | Neutralized to 0.0, declared in §2 — no retrospective data enters |
| Market prices | Never enter (no market leg; corpus line columns unused, §4) |
| Outcomes | Realized scores, used only after prediction |

## 4. Data provenance

- Corpus: nflverse schedule data (`games.csv`, nflverse/nfldata),
  acquired 2026-10-15 from the project's canonical public source.
  Local file `~/workspace/tmp/bt_data/nfl_games.csv`, SHA-256
  recorded in `DATASET_MANIFEST_STAGE2.md` (the evaluator verifies
  the hash at load and refuses a mismatched file). 7,548 games,
  all seasons in the file; fields used: season, game_type,
  gameday/gametime, away/home team, away/home score. **The file
  also carries spread/total/moneyline columns (single-source
  closing lines); they are not read by the evaluator** — see the
  headnote on why the market classification stands.
- **The corpus is NOT in the repository** (third-party data);
  the manifest records source, acquisition path, and hash, as in
  Stage 1.
- No sealed window exists for this evaluation (the MLB sealed
  window was a property of the Lane A holdout design, not of this
  one); no games are held out — this is development-data
  calibration evidence, labeled as such.

## 5. Population, metrics, and the predeclared bars

- **Population:** corpus games with game_type == REG, seasons
  **2018–2025**, final scores present. Every such game is scored
  (week-1 fixtures carry 0.0 ratings by the production rule and are
  included — that is what the engine does live). Expected n ≈
  2,100; the exact count and per-season counts are reported.
- **Baselines (both expanding, strictly prior, same-season):**
  - **B1 — league margin climatology:** empirical distribution of
    home margins over prior same-season games.
  - **B2 — league total climatology:** empirical distribution of
    game totals over prior same-season games.
  - Climatology eligibility: ≥ 30 prior same-season games, else
    the fixture is excluded from the paired comparisons and
    counted (model-only scores still reported). Expected to bite
    only in the opening weeks of each season.
- **N1 (moneyline):** model P(home win) = the Lane A view's win
  probability (push mass excluded; realized ties score y = 0 for
  the win event, declared here). Brier and log loss (clamp 1e-15)
  vs B1's implied P(home margin > 0) from the empirical margin
  distribution. **Gate:** BEATS_BASELINE iff pooled paired ΔBrier
  CI entirely < 0 AND ΔLogLoss CI entirely < 0.
- **N2 (spread):** margin-distribution CRPS — Normal CRPS in
  closed form for the model; empirical CRPS for B1. **Gate:**
  BEATS_BASELINE iff pooled paired ΔCRPS CI entirely < 0.
  Descriptive: calibration of P(home win) in deciles; cover Brier
  at the fixed half-line grid {−7.5, −3.5, −2.5, −1.5, −0.5, +0.5,
  +1.5, +2.5, +3.5, +7.5} vs B1's cover probabilities (no market
  lines are used; the grid is declared here).
- **N3 (total):** total-distribution CRPS vs B2 (same closed-form /
  empirical pairing). **Gate:** BEATS_BASELINE iff pooled paired
  ΔCRPS CI entirely < 0. The §1 caveat rides on every N3 table.
- All CIs: paired per-game differences, 95% percentile, block
  bootstrap over ISO calendar weeks, 2,000 resamples, seed
  20261015. Pooled and per-season reporting; each of N1/N2/N3 is
  verdicted separately (BEATS_BASELINE / DOES_NOT_BEAT_BASELINE).

## 6. Verification required before any verdict is reported

- **Parity (the M2 §9 pattern):** for the first 25 scored games,
  `calculate()` driven with ML, SPREAD (−3.5), and TOTAL (44.5)
  rows over the corpus-backed provider must return Lane A views
  whose probabilities equal the direct
  `context_for` → `score_means` → `model_probability` pipeline to
  < 1.5e-6. If `calculate()`'s Lane A path adds anything the direct
  construction lacks (e.g. a form term), parity fails, the run
  stops, and the discrepancy is reported instead of a verdict.
- **Determinism:** a full re-run reproduces the results JSON
  exactly except `generated_at`.
- **Population reconciliation:** scored + excluded counts reconcile
  to the corpus's REG-game count for 2018–2025, by season.

## 7. What verdicts do and do not unlock

Calibration evidence about the football rating construction on
2018–2025 development data. A pass does not create a market
verdict (none is possible historically under the paired standard),
does not touch the G2 program (Attempt 2 remains the owner's
separate ruling, unspent), and does not change any card status —
NFL rows keep their current labels, including
`WATCH_NFL_TOTAL_PRIOR_ONLY` for totals whatever N3 shows. A fail
is reported in full and feeds the refine/recalibrate record.
