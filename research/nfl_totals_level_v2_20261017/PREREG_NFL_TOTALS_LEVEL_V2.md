# PREREGISTRATION — NFL Totals LEVEL v2 (recency + cross-season carryover)

**Status: written and hash-locked BEFORE any v2 candidate score was
computed, on any data.** The evaluator in this directory verifies this
file's SHA-256 against `SPEC_HASHES.txt` at load and refuses to score
on a mismatch.

- **Written:** Sat 2026-10-17 (CT), by Claude under Isaac's
  DIRECTIONS_FOR_CLAUDE §5.2.1 ("fit a scoring LEVEL … each successor
  hypothesis needs a NEW preregistration before scoring").
- **Label of any output:** RESEARCH_EVIDENCE. Part A is a
  retrospective DIAGNOSTIC SCREEN on reused development data; Part B
  is a prospective calibration test. Neither is a market verdict,
  neither is validation, neither is a promotion input. No production
  model, registry, card label, threshold, or the
  `WATCH_NFL_TOTAL_PRIOR_ONLY` disposition changes because of this
  work. Any wiring or promotion is a separate ruling by Isaac.

## 0. Why this exists, and what is new

The LEVEL v1 candidate (branch `research/nfl-totals-level-model-20261016`
@ `1d5af15bf`, prereg SHA-256 `de83468b…`) verdicted
**DOES_NOT_BEAT_BASELINE** (CRPS 7.7606 vs B2 7.7126 vs FROZEN
7.8225, n = 1,887). Its own error decomposition named the binding
error: **level tracking**. Per-season level bias swung from −2.13
(2020) to +2.67 (2023); variance (resid sd 13.77 vs 13.5) and
team-split (error correlation −0.002) contributed nothing. v1 was a
same-season expanding average that restarted every September.

v2 tests ONE hypothesis: **a level estimate that moves faster
(exponential recency weighting) and does not restart (decayed
cross-season carryover) beats the frozen prior AND both climatology
baselines on the game-total distribution.** The total sd stays FIXED
at 13.5 and the distribution stays Normal, so the test isolates the
level. (Shape — key-number multimodality — is the second named
hypothesis and is deliberately NOT in this construction.)

The reproduction of v1 was re-derived independently before this file
was written: re-running v1's evaluator on the manifested corpus
reproduced v1's results JSON byte-for-byte except `generated_at`.

## 1. Data

- **Corpus (Part A):** nflverse `nfldata` `data/games.csv`, the exact
  Stage 2 bytes, SHA-256
  `a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284`
  (recoverable from nflverse/nfldata commit
  `4c15d52430866a57c1e7118177d8aea2e0905ab0`, 2026-10-15T07:35:13Z;
  verified at load). Not in this repository (third-party data).
- **Fields read:** season, game_type, gameday, gametime, away_team,
  home_team, away_score, home_score. Spread/total/moneyline columns
  are NEVER read.
- **Input window:** REG games only. A fixture in season S may use
  inputs from seasons S−1 and S only (strictly before kickoff).
  2017 REG games are loaded as burn-in INPUTS for 2018 fixtures and
  are never scored.

## 2. Arms (identical fixtures)

1. **FROZEN** — the production prior as shipped: `artifacts/free_models.py`
   blob `253b0c6d91840c906941216be117f2acc1497a57` (verified at load),
   Stage 2 construction verbatim (≤5-game margin rating, 22-pt base,
   Normal(·, 13.5), injury/weather neutralized 0.0).
2. **B2** — Stage 2 league total climatology: empirical distribution
   of strictly-prior SAME-SEASON game totals; empirical integer CRPS.
3. **B3 — two-season climatology (NEW baseline, added because v2
   carries information across seasons and must beat the naive version
   of doing so):** empirical distribution of game totals over ALL
   REG games of season S−1 plus strictly-prior REG games of season S,
   equal weight per game; empirical integer CRPS (same construction
   as B2).
4. **CANDIDATE — LEVEL v2** (`sportsedge/research/nfl_totals_level_v2.py`):
   - League level L(t) = exponentially weighted mean of (game total /
     2) over all strictly-prior games in the input window, ordered
     chronologically; a game of age k games (0 = most recent) has
     weight 0.5^(k / **128**). Empty history → 22.0.
   - For every input game g of team T, record
     off_res = PF − L(t_g) and def_res = PA − L(t_g), where L(t_g) is
     the league level strictly before g's kickoff (no lookahead).
   - Team residuals at fixture time: weights 0.5^(k / **6**) by
     team-game age k, times **0.5** per season boundary crossed
     (prior-season games × 0.5); shrunk toward 0 with **κ = 3.0**:
     off_T = Σ w·off_res / (Σ w + 3), def_T likewise.
   - E_home = L + (off_H + def_A)/2 + 0.75;
     E_away = L + (off_A + def_H)/2 − 0.75.
   - Total ~ **Normal(E_home + E_away, 13.5)**; closed-form Normal CRPS.
   - Every constant (128, 6, 0.5, 3.0, 22.0, 0.75, 13.5) is fixed
     here, chosen before any v2 score existed, and is never adjusted.
     They were picked as conventional magnitudes (≈ 8 weeks of league
     games; ≈ 6 team-games; half-weight across one offseason; κ near
     v1's 4), NOT by fitting.

## 3. Part A — DIAGNOSTIC SCREEN (reused development data)

- **Population:** REG 2018–2025 with final scores; paired subset =
  fixtures with ≥ 30 strictly-prior same-season games (Stage 2
  eligibility; expected n = 1,887). Identical-kickoff batch rule.
- **Reproduction precondition:** the evaluator first re-derives
  Stage 2's FROZEN and B2 numbers on the paired subset (7.8225,
  7.7126, Δ +0.1099 [+0.0283, +0.1987], each within 1e-3). Failure
  stops the run with no candidate verdict.
- **Scoring:** total CRPS; paired per-game differences; 95%
  percentile CIs by block bootstrap over ISO calendar weeks, 2,000
  resamples, seed 20261015 (Stage 2 algorithm).
- **Screen gate:** SCREEN_PASSED iff the pooled paired ΔCRPS CI is
  entirely < 0 vs FROZEN **and** vs B2 **and** vs B3. Otherwise
  **DOES_NOT_BEAT_BASELINE**, failing legs named; the v2 construction
  is then CLOSED (no Part B, no re-tuning).
- **Why only a screen:** 2018–2025 has now informed two prior NFL
  totals evaluations and the v1 diagnosis that motivated v2. A pass
  here cannot be called out-of-sample validation. It only earns the
  right to a test on data no one has scored.
- **Descriptive (no gate):** per-season Δ vs each arm with CIs (any
  losing season is named); level mean signed error per season; OVER
  Brier at {37.5, 40.5, 43.5, 46.5, 49.5, 52.5}.

## 4. Part B — PROSPECTIVE TEST (2026, untouched)

Runs only if Part A is SCREEN_PASSED.

- **Population:** 2026 REG games with kickoff **≥ 2026-10-18T00:00
  America/New_York** (all of them are after this file's lock),
  through the final 2026 REG game. All have ≥ 30 prior same-season
  games, so all are paired-eligible. Earlier 2026 games and all of
  2025 are inputs only.
- **Corpus:** the nflverse `games.csv` snapshot pulled once after the
  last 2026 REG game is final. Its SHA-256 is recorded in the result.
  Only the §1 fields are read.
- **Scoring:** one scoring run, after season end. No interim peeking
  at the scored subset. Arms, metric, bootstrap, and seed are
  identical to Part A.
- **Gate (unchanged from Part A):** BEATS_BASELINE iff the pooled
  paired ΔCRPS CI is entirely < 0 vs FROZEN, B2, and B3.
  If every leg's point estimate favors the candidate but at least one
  CI crosses zero, the verdict is **INCONCLUSIVE**, stating the
  sample at which the observed effect would be resolvable. Otherwise
  it is DOES_NOT_BEAT_BASELINE.

## 5. Market leg — NOT in this preregistration

BEATS_BASELINE on Part B is a calibration result only. The totals
family cannot become PLAY-eligible without a market leg against
contemporaneous de-vigged two-sided main totals, scored under its own
preregistration. That prereg is written only if Part B passes. It is
not implied here, and nothing in this file lowers that bar.

## 6. Point-in-time audit

| Input | Rule |
|---|---|
| League level L(t) | Strictly-prior games only; identical kickoffs batched |
| Residual anchors L(t_g) | Computed strictly before each input game g |
| Team residuals | Strictly-prior team games; seasons S−1, S only |
| B2 / B3 pools | Strictly prior; B3 adds only completed S−1 games |
| Injury / weather | Not used (no PIT source); FROZEN keeps Stage 2's 0.0 neutralization |
| Market lines | Never read |

## 7. Verification required before any verdict is reported

- The reproduction precondition (Part A).
- **Unit checks** (tests in `tests/test_nfl_totals_level_v2.py`):
  empty-history fallbacks; half-life weight identities; carryover
  factor; no-lookahead (a residual anchor never uses its own game).
- **Independent hand check:** on ≥ 10 fixtures, recompute the
  candidate total mean from the raw corpus with code that does not
  import the candidate module; agreement < 1e-9.
- **Determinism:** a re-run reproduces the results JSON except
  `generated_at`.
- A separate verifier who did not write the evaluator re-runs it from
  a fresh worktree of the pushed head before the verdict is reported
  as final.
