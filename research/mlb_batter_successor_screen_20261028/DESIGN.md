# DESIGN — MLB_BATTER_RATES_V1 (MLB batter successor construction)

**Status: DESIGN — written before any fitting, per the binding conditions of
the SmartStake admission (PR #2888). This document is the preregistration for
the historical screen executed in this packet. One run, in the configuration
declared here; no tuning after the fact.**

## 1. Identity and scope

- **Construction:** `MLB_BATTER_RATES_V1` — a new construction. It is the
  successor candidate for the retired MLB batter incumbents; it reuses none of
  their code, features, or fitted state. The incumbents stay retired.
- **Data:** SmartStake `mlb-player-props` (Hugging Face), pinned revision
  `7cedfd3fe29f2de4f675039410a48160739323fc`, admitted DESIGN/SCREEN ONLY by
  PR #2888 (`research/mlb_smartstake_props_admission_20261028/`). All 18
  partitions were verified at admission by size + sha256 against the canonical
  LFS oids; this screen consumes the staged, pin-verified copies and
  re-verifies the pins before use.
- **Scope labels (binding):** this screen earns **no validation credit, no
  clock credit, no play eligibility**. Market comparisons are labeled
  **"vs-close (timestamped, per book)"** — never "verified CLV."
  A DESIGN_PASS here means only: eligible for a prereg draft under the
  program's forward rules.
- **Season:** 2026 only (games 2026-03-21 → 2026-07-05), the only season the
  admitted source carries.
- **Markets (all six admitted):** player bases, player hits, player rbis,
  player home runs, player strikeouts, player batting walks.
- **Attribution:** CC BY 4.0 — SmartStake.

## 2. Population and evaluation unit

- **Close book:** DraftKings (`draftkings`), present in all 18 partitions.
  The construction is scored against the DraftKings close; other books are
  not used.
- **Evaluation unit:** one selection = (game, player, market) at its
  DraftKings **main line** in the validation window with a graded result.
- **Main line (deterministic, pre-committed):** among the lines DraftKings
  quoted for the selection, the line with the largest total quote count
  (over + under rows). Ties break to the line whose de-vigged closing over
  probability is closest to 0.50; further ties to the lower line. (Measured
  motive: 86% of selections carry more than one quoted line — alternates must
  not be scored as independent selections.)
- **Close (per the admission's recipe):** for the main line, the last quote
  per side before game start. The admission verified every quote in the
  source satisfies `ts < start_time`, so the last quote per
  (book, market, player, line, side) is unambiguously the close. Both sides
  must be present at the main line or the selection is excluded and counted.
- **Strikeouts population disclosure:** at DraftKings the
  `player strikeouts` market is populated by **pitchers**, not batters
  (measured on the April partition: 100 distinct strikeout players, 1 also
  present in the hits market; line mass centered at 4.5–5.5). The leg is
  screened as admitted — same machinery, population = the players
  DraftKings posts in that market — and is labeled a pitcher-population leg
  in every result table. It is not represented as a batter market.

## 3. Features — point-in-time safety

The dataset carries no lineup, plate-appearance, weather, or matchup fields,
and this construction uses **none**. The market's own prices are **never**
features; the close appears only as a baseline (§5).

For a target game G and market M, the only inputs are:

- the player's **strictly-prior appearances** in market M: every
  (game, player, M) group with a graded `result` whose `start_time` is
  strictly before G's `start_time` (2026 season only — no other season
  exists in the admitted source). A prior game's `result` is a completed,
  publicly known outcome before G's first pitch, so this is point-in-time
  safe; the admission additionally verified the source contains no
  post-start quotes at all.
- league constants (μ, φ) fitted on the fit window only and frozen (§6).

Playing-time exposure is implicit: an appearance exists only where
DraftKings posted the market for that player in that game. Rates are
therefore per posted appearance (≈ per game in the lineup). This is a
declared approximation, not a hidden one.

## 4. Probability model

For each market independently:

- League mean μ_M and dispersion φ_M are estimated on the **fit window**
  from per-appearance results: μ = mean(result); φ = max(1, var/mean),
  capped at 2.5.
- Player rate, shrunk toward the league mean with prior weight **K = 20
  appearances**:
  `λ̂ = (Σ prior results + K·μ_M) / (n_prior + K)`.
  A player with no prior appearances gets λ̂ = μ_M.
- Count law: Negative Binomial with mean λ̂ and variance φ_M·λ̂ when
  φ_M > 1.02, else Poisson(λ̂).
- `p_over = P(X > line)`, `p_under = 1 − p_over` under the same law
  (all observed lines are half-points; if an integer line ever appears,
  the push mass `P(X = line)` is carved out and pushes are excluded from
  scoring and counted — declared here, expected count zero).

Features for validation-window games use the **expanding strictly-prior**
window (fit window plus any earlier validation-window games) — exactly how
the construction would run live — while μ and φ stay frozen at their
fit-window values.

## 5. Baselines

Both baselines are scored on the identical evaluation units.

1. **Market close (DraftKings), "vs-close (timestamped, per book)":**
   de-vigged closing probability at the main line,
   `p_over = (1/o_over) / (1/o_over + 1/o_under)` from the closing decimal
   odds.
2. **Simple rates baseline:** the same count law (§4) with λ = μ_M for
   every player — league rates only, no player information. This is the
   "does player identity carry any signal at all" bar.

## 6. Chronological split (preregistered, per admission condition 1)

- **Fit window:** games with `start_time` in [2026-03-21, 2026-06-01).
  Only μ_M and φ_M are fitted here.
- **Validation window:** games with `start_time` in [2026-06-01,
  2026-07-06) **with a graded result**. Declared caveat (from the
  admission): the source grades **no July games** (odds-only by design),
  and June is a partial month (243 distinct games dataset-wide). The
  graded validation set is therefore June 2026 — roughly a 240-game
  window, not two full months. No other fold exists inside one partial
  season; the screen is a single chronological fold and says so.

## 7. Pre-committed criteria and verdict rule

Scoring is by proper scoring rules on the over outcome
`y = 1{result > line}`: log loss (primary) and Brier score (reported).
Deltas are paired per selection. Uncertainty: cluster bootstrap by
`game_id`, 2,000 resamples, seed 20261028, two-sided 95% percentile CI.

Per market, on the validation window, the construction must satisfy **all**
of:

- **C1 (n):** at least **300** graded evaluation selections.
- **C2 (vs market):** Δ log loss (model − market close) has 95% CI upper
  bound **< 0**.
- **C3 (vs simple rates):** Δ log loss (model − simple rates) has 95% CI
  upper bound **< 0**.
- **C4 (calibration):** |mean predicted p_over − observed over rate| ≤
  **0.04**.

**Verdict rule (exactly one applies, in this order):**

- **FAILED_SCREEN** — any market meets C1 and fails any of C2–C4. The
  construction is retired; no tuning follows.
- **NOT_EXECUTABLE** — no market fails, but at least one market cannot be
  judged (C1 unmet, or the evaluation set cannot be built). The missing
  piece is named.
- **DESIGN_PASS** — all six markets satisfy C1–C4. Meaning: eligibility
  for a prereg draft. Nothing more (§1).

## 8. Declared limitations

- One partial season, one fold. A pass would rest on ~240 June games.
- No lineup/PA/matchup/park/weather inputs exist in the admitted source;
  the market close embeds all of them. C2 is therefore a genuinely hard
  bar, set deliberately: a construction that cannot beat the close on a
  proper score has no forward case.
- Rates are per posted appearance, not per plate appearance; players who
  enter mid-game or sit after being posted add noise the model cannot see.
- Prior MLB screens' lesson (MLB_GAME_STATE_V1, #2905) is noted: richer
  state did not beat simpler constructions there. This design is
  deliberately minimal — player rates + shrinkage + dispersion, nothing
  else.
