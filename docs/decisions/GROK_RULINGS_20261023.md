# Grok rulings recorded for the completion gap ledger (Oct 23, 2026 CT)

Recorded by Grok under the owner's delegation ("You make all rulings", Oct 22,
2026). No earlier repo record of these decisions existed; this file is that
record. Research-only; nothing here validates any family or grants play.

## ruling-6-focus-pause

Dated Oct 22, 2026. NHL attempt 2, NBA secondary props and MLB game-line
commissioning are paused until the first completed verdict review in NFL props
or NBA props (expected mid-to-late November 2026 at the earliest). In the
canonical MLB/NFL scope this pauses: F5_MONEYLINE, F5_RUN_LINE,
F5_TEAM_TOTALS, F5_TOTALS, NRFI, YRFI. NFL Part 2/2B, the ATD freeze package,
the passing-yards screen, NBA props V1/V2 and NBA team totals continue.

## owner-hold-either-pitcher-20261015

Dated Oct 15, 2026 (owner ruling, recorded here by Grok). EITHER_PITCHER
pricing (EITHER_PITCHER_BB, EITHER_PITCHER_ER, EITHER_PITCHER_HITS_ALLOWED)
stays refused until the underlying pitcher marginals are repaired. Matches the
gate EITHER_PITCHER_MARGINAL_TAIL_ERROR in sportsedge/canonical_coverage.py.

## MLB pitcher Infrastructure gaps are already covered (2026-10-23)

Grok ruling under owner t234u/t242u. PITCHER_K, PITCHER_BB, PITCHER_ER and
PITCHER_HITS_ALLOWED were listed as NO_FORWARD_TEST_CONFIG. All four are covered by the
committed, frozen one-shot study `docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md` (v2,
2026-10-04; DK PIT quote archive, run once after the 2026 postseason), and PITCHER_K also
by `config/research/mlb_pitcher_k_forward_validation_v1.json`
(FROZEN_BEFORE_FIRST_PROSPECTIVE_PREDICTION). `PROGRAM.md` already records "no duplicate
instruments" for this set. No new forward-test config is built; neither frozen instrument
is modified. Status COVERED_BY_COMMITTED_FROZEN_INSTRUMENT is structural only: no score
points, nothing validated, play_allowed false.
