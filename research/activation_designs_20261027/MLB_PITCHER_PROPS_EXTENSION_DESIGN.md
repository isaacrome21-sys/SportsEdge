# MLB pitcher props EXTENSION — construction design + preregistration draft

**Status: DESIGN ONLY — preregistration DRAFT, not frozen. No clock, no
counted rows, no verified claim, no PLAY.** Markets in scope, and only these:
`PITCHER_PITCHES` (registered v2 as `PITCHER_PITCH_COUNT_V2` in
`sportsedge/mlb_family_registry_v2.py`), `PITCHER_HITS_WALKS_ER` (hits + walks
allowed combo), and the `EITHER_PITCHER_*` variants (hits allowed / walks /
earned runs for either starter). Out of scope by design: PITCHER_K (its ridge
protocol runs untouched; K/BB/ER/hits-allowed are bound by the frozen Oct 4
promotion prereg), and PITCHER_OUTS (bound by the Oct 20 forward draft). This
extension exists because the markets above are the registered pitcher markets
no instrument covers.

## Current state (honest)

The wired joint empirical-Bayes engine prices the sibling markets, and
PITCHER_PITCHES is wired behind a measured-pitch-count requirement — but its
registered market resolution carries `validation_status =
DOES_NOT_BEAT_BASELINE`. The incumbent is therefore a baseline to beat, not a
construction to extend. There is no historical line archive for pitch-count
or combo props (Gap G1): the Oct 4 study's archive covers its four markets
only. The market leg of any validation for this family is necessarily
forward-captured DraftKings prices, which in practice means the 2027 season.

## Edge mechanism

Pitch counts are where the book's line is most mechanical: DK's pitch lines
track a starter's recent average with shallow adjustment for who he is
facing. The construction prices the *workload chain*, not the average:

projected batters faced (BF) distribution → pitches per BF, conditioned on
the opposing lineup's actual pitch-taking profile (pitches/PA by lineup slot,
foul-off rate) and the starter's own pitch economy → pitch-count
distribution; outs, hits allowed, and walks allowed fall out of the same
chain (outs per BF, hit/walk rates per BF), which is what makes the combo
and either-pitcher variants coherent instead of three separate guesses.
Umpire strike-zone tendency (called-strike rate) enters as a bounded
adjustment to pitches/BF. None of these inputs is a price; no closing line,
consensus, or same-game outcome is an input.

## Construction (v1, bound by this draft)

1. **BF model.** Starter BF distribution from strictly-prior starts:
   recent BF mean/variance, hook propensity (manager/team quick-hook rate),
   opponent lineup strength, and game-state expectation (expected score
   differential from team run environments — design inputs only, no market
   numbers). Distribution: discretized empirical with a negative-binomial
   smoothing, parameters fixed at freeze.
2. **Pitches/BF.** Starter's strictly-prior 30-day Statcast pitches/BF,
   shrunk toward his season rate, adjusted multiplicatively by the announced
   lineup's aggregate pitches/PA deviation from league (the same
   announced-lineup contract the frozen K prereg uses; neutral when the
   lineup is unavailable, counted as a degraded row).
3. **Per-BF outcomes.** Hit and walk rates per BF from strictly-prior
   StatsAPI game logs + Statcast quality-of-contact allowances, shrunk
   toward league-by-handedness rates.
4. **Outputs.** Full count distributions for pitches, outs, hits allowed,
   walks allowed per starter; either-pitcher variants computed as the
   distribution of the maximum across the two starters (never the sum, never
   a per-side independence assumption); the hits+walks combo as the joint
   sum from the same simulated BF sequence.

## Inputs (admitted sources only)

- MLB StatsAPI game logs and box scores (primary in-repo source).
- Baseball Savant / Statcast pitch-level data via pybaseball (admitted for
  convenience parity; design extracts pinned by sha256 at design time —
  Savant data is subject to retroactive correction).
- Announced lineups under the existing strictly-prior lineup contract.
- Forward DraftKings captures (T-1H + FINAL lane writes) as the ONLY market
  baseline. No historical prop-line source is claimed, because none exists.

## Validation protocol (fixed in advance; one look)

**Stage S — design screen (runs on design data; decides only whether this
draft advances to a freeze request).** Reconstruct 2025–2026 starts under
the K prereg's PIT discipline (30-day Savant window ends at the official
game date; rows missing a required input fail closed and are counted).
Compare the construction's pitch-count and outs distributions against the
incumbent joint empirical-Bayes engine on identical rows. Screen pass =
mean log loss on pitch counts better than the incumbent's AND calibration
slope within [0.8, 1.25] on the pooled screen. A failed screen is recorded
FAILED_SCREEN and this version stops; the data it saw becomes design data
for any successor. The screen is design evidence, never validation.

**Stage V — promotion validation (the verified test, after an owner
freeze).** Universe: every paired DK offering in the three scoped markets,
captured pregame under the lane cadence, over the first 60 days of the 2027
regular season, minimum 300 priced pitcher-games (if the minimum is not met
by day 60, the window extends to the day it is met — extension rule fixed
here, criteria unchanged). Primary metric: mean log loss of the
construction's distributions vs (a) the incumbent EB engine's probabilities
on the same rows and (b) DK no-vig probabilities from the FINAL capture.
PASS = the construction beats BOTH baselines on the primary metric, with
the paired one-sided comparison significant at alpha = 0.05 / k (k =
validated families at verdict time), and calibration slope within
[0.8, 1.25]. One look, at window close. CLV and ROI are graded and reported
throughout but do not gate the verdict (owner ruling, Oct 27, 2026).

## Activation state on landing

DESIGN ONLY. Executables owed before any freeze request: the workload-chain
engine, the PIT reconstruction harness for Stage S, and DK pitch-prop
capture confirmation (the lane grammar already carries pitcher props from
the DK event page; pitches/combo/either-pitcher lines must be confirmed
present in captures, in the comment block where the parser cannot read them,
before the 2027 window is scheduled).

## Blockers

- Stage V cannot start before the 2027 season (no forward DK pitch-prop
  captures exist to validate against) — structural, not a data gap to hunt.
- Either-pitcher and combo lines must be confirmed in DK's rendered market
  surface at capture time; any variant DK does not post drops out of the
  universe by the paired-offering rule, silently and without substitution.
