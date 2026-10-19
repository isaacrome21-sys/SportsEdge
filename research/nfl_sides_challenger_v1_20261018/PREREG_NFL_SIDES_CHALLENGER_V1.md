# PREREGISTRATION — NFL sides (moneyline): margin-of-victory Elo challenger vs the closing market and vs Elo v1

**Status: written and hash-locked BEFORE any score of this construction exists on any data.**
Written Sun 2026-10-18 (CT). Label of any output: **SCREEN** (research only).

**This is a SECOND ATTEMPT on used data.** The 2018–2025 closing lines in §1 were
already scored by NFL sides Elo v1 (DOES_NOT_BEAT_CLOSE, both markets) and by the
NFL totals LEVEL work. Under the owner's version-scoring rule (Oct 18, 2026),
a construction scored on games it was designed after seeing is a **screen**,
never a validation, whatever the outcome. Even a BEATS_CLOSE result here is a
screen result: it earns, at most, a forward test on 2026 DraftKings captures.
No output of this run is PLAY-eligible, and no pick of this challenger may be
promoted to a card source on the basis of this run.

## 0. Why
The incumbent card-side heuristic (22 pts/team prior + bounded form) compresses
probabilities toward 0.5 and surfaced 20/20 underdogs as "edges" on Oct 17
(#2383/#2384). Elo v1 — a fixed-constant published Elo — failed against the
close on the same window (moneyline Δ log loss +0.0274 [+0.0188, +0.0356],
n = 2,219, regular + postseason). This challenger asks the one remaining
narrow question for a pure rating model: does a margin-of-victory Elo whose
Elo→probability and Elo→points mappings are **calibrated on pre-window data
only (2010–2017)** and then frozen do any better on 2018–2025 than (a) the
closing market and (b) Elo v1 itself? Every constant in §2 is fixed here from
the published FiveThirtyEight NFL Elo method or fit on 2010–2017 only; none is
tuned on the scored window.

## 1. Data
nflverse/nfldata `games.csv`, SHA-256 `a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284`
— the identical pinned vintage Elo v1 used (the live nfldata file has since
drifted; the scorer in §7 refuses to run on any other hash). Fields used:
season, game_type, week, gameday, gametime, game_id, home_team, away_team,
home_score, away_score, location, home_moneyline, away_moneyline, spread_line.
The lines are nflverse consensus CLOSING lines, not DraftKings quotes, and
carry no capture timestamps: this is a retrospective comparison to the closing
market, not point-in-time execution evidence. Closing lines are used exactly
as recorded in the pinned file; no line is fabricated or reconstructed.

Team identity is the file's team code. A code first appearing mid-stream
(expansion or relocation, e.g. LA 2016, LAC 2017, LV 2020) starts at the base
rating in its first game. This is a declared limitation, shared with Elo v1's
code-keyed engine.

## 2. Challenger (all constants and procedures fixed here)
Rating stream: every game in the file (regular season + postseason), seasons
1999–2025, ordered by (gameday, gametime, game_id). Games with identical
kickoff are rated from the same pre-kickoff state, then updated together
(the batching semantics of the Elo v1 evaluator).

- Base rating 1500 for every team at stream start and for any team code on
  first appearance.
- Between seasons: regress every rating 1/3 toward 1500.
- Home field: +48 Elo to the home team, 0 when `location == "Neutral"`.
- Pregame difference: d = elo_home + HFA − elo_away.
- Update after each batch: expected home score E = 1/(1 + 10^(−d/400))
  (the standard Elo expectation; used ONLY for rating updates). Result
  S = 1 (home win), 0 (away win), 0.5 (tie). Margin-of-victory multiplier
  = ln(|margin| + 1) · 2.2 / (0.001 · elo_diff_winner + 2.2), where
  elo_diff_winner is the winner's pregame difference (d if the home team
  won, −d if the away team won); multiplier = 1 for ties. Shift =
  K · multiplier · (S − E) with K = 20; home rating += shift, away −= shift.
  Ratings for a game use only prior games (strictly chronological).
- Calibration mapping — fitted on 2010–2017 ONLY, then frozen:
  - Fit set: every stream game with season 2010–2017, with its pregame d
    recorded before that game's update.
  - Points: ordinary least squares margin = a + b·d over the fit set
    (ties included, margin 0). Predicted margin for any later game = a + b·d.
  - Win probability: logistic regression of home win on d (intercept α,
    slope β), maximum likelihood, no regularization; ties EXCLUDED from
    this fit. P(home win) = 1/(1 + e^(−(α + β·d))).
  - The fitted (a, b, α, β) are outputs of this frozen procedure, recorded
    in the results file. They are never refit on, or adjusted using, any
    2018–2025 data.

## 3. Arms (identical scored rows)
- CHALLENGER: §2.
- MARKET: de-vigged closing moneyline, proportional (multiplicative)
  normalization of the two implied probabilities (the Elo v1 method).
- ELO_V1: the Elo v1 construction exactly as frozen in
  `PREREG_NFL_SIDES_ELO_V1.md` (base 1505, stream from 2015, HFA +48,
  K = 20, same MOV multiplier, P(home) = 1/(1 + 10^(−d/400))), recomputed on
  the same pinned corpus with code carried from its evaluator, and compared
  on the identical scored rows of §4. Its published full-set verdict
  (regular + postseason: Δ +0.0274 [+0.0188, +0.0356], n = 2,219,
  DOES_NOT_BEAT_CLOSE) is cited for reference; the head-to-head here is on
  the §4 regular-season rows, which is stated wherever the comparison is
  reported.

## 4. Scored set
Season 2018–2025, `game_type == "REG"`, both closing moneylines present,
home_score ≠ away_score (ties excluded from moneyline log-loss scoring).
Expected n = 2,119 (2,127 regular-season games − 8 ties); the actual n is
recorded in the results.

## 5. Metrics and gates
- Per-game log loss of the home-win event for each arm, probabilities
  clipped to [1e-12, 1 − 1e-12].
- Paired per-game Δ log loss; 95% CI by block bootstrap over (season, week)
  blocks, 2,000 resamples, seed 20261018 (the Elo v1 bootstrap procedure).
- **Gate 1 (primary, vs the close):** BEATS_CLOSE iff the CI for
  (CHALLENGER − MARKET) lies entirely below 0; otherwise DOES_NOT_BEAT_CLOSE.
- **Gate 2 (vs the incumbent rating model):** BEATS_ELO_V1 iff the CI for
  (CHALLENGER − ELO_V1) lies entirely below 0; otherwise DOES_NOT_BEAT_ELO_V1.
- Descriptive only: (ELO_V1 − MARKET) Δ on the same rows, so the three arms
  can be read together.
- Expected outcome stated in advance: closing NFL markets are efficient and
  a public rating model is not expected to beat them; a fail is the expected
  result and closes the pure-rating line of attack for sides.

## 6. Descriptive readouts (no gate)
- **ATS readout:** candidate rows in the scored set with spread_line present
  and |predicted margin − spread_line| > 3 (strictly). Candidate side =
  home if the difference is > 3, away if < −3. Games whose actual margin
  equals spread_line (push) are excluded. Report n and the candidate side's
  cover rate.
- **Favorite/underdog diagnostic (required):** for the §6 candidate rows
  with spread_line ≠ 0, the closing favorite is the home team if
  spread_line > 0, the away team if spread_line < 0 (nflverse spread_line
  is the home team's expected margin). Report: n candidate rows; how many
  back the underdog and the favorite (counts and shares of the non-pick'em
  candidate rows); pick'em candidate rows (spread_line == 0) counted
  separately; and the challenger's mean log loss and paired Δ vs MARKET
  (with the §5 bootstrap CI) within the favorite-backed subset and within
  the underdog-backed subset. This split is the diagnostic for the
  incumbent's known underdog-compression defect.

## 7. Procedure and integrity
- The scorer verifies the corpus SHA-256 (§1) and this document's SHA-256
  (SPEC_HASHES.txt, committed with this document) before scoring and
  refuses to run on any mismatch.
- The scorer is deterministic: two runs must produce byte-identical
  results; the run is executed twice and the identity recorded.
- Any change to §2, §4, §5, or §6 after this freeze is a new version of
  this preregistration, committed with the reason recorded, BEFORE any
  re-scoring. No parameter is adjusted after seeing scored output.

## 8. What a pass would and would not mean
A BEATS_CLOSE here is a SCREEN pass on reused data. It would justify, at
most, freezing this construction for a prospective forward test against
2026 DraftKings captures under the capture spec — the only route by which
a side model can be validated in this project. It does not lift any hold,
does not make any pick PLAY-eligible, and does not change which model
sources cards.
