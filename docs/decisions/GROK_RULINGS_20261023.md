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

## Quarter spreads refused as moneyline-derivable (2026-10-23)

Grok ruling, Option 1, dated Oct 23, 2026, on the t248 NOT CLEARED finding. In
`sportsedge/nfl_period_lines_empirical.py` the quarter margin pmf is the public
history's pooled margin pmf moved by one shift. Any public quarter spread price (even
+/-1.5) plus that history pins the shift by bisection, and so rebuilds the refused
NAIVE_FAIL quarter moneyline exactly. Every Q1-Q4 spread is therefore refused with
`NAIVE_FAIL:Qn_MONEYLINE_DERIVABLE`; all quarter spreads were inconclusive versus naive
in the screens anyway, so no screen-supported market is lost. Public Q1-Q4 output carries
only identifiers, governance and refusal codes, plus the Q2 total and its `total_pmf`
(Q2_TOTAL was not refused); margin pmfs, team means and refused total pmfs are dropped.
H1/H2 are unchanged. Screens run through the guarded unrestricted path and reproduce
byte for byte. Test: `tests/test_nfl_period_lines_bisection_rebuild_20261023.py` runs
the bisection rebuild against every public output. Ledger: no status changes (its
quarter rows track the wired PERIOD_DERIVATIVE engine, not this screen engine). SCREEN /
NOT_VALIDATED, play_allowed false; nothing validated.

## DK-API workflows are manual-only (2026-10-23)

Grok ruling dated Oct 23, 2026, under owner delegation t234u, enforcing the owner's
invariant that DraftKings data comes from rendered pages only. Seven workflows import or
run a module that builds a DraftKings API URL (`/sites/US-SB/api`,
`sportsbook-nash.draftkings.com/api`): draftkings-prop-provider-probe,
mlb-prop-pit-archive, nfl-market-maker-radar-capture, mlb-moneyline-forward-evidence,
nfl-2026-line-capture, nfl-dk-direct-confirmation-capture and
sportsedge-auto-dk-four-sports. On all seven the cron lines are deleted and the push,
pull_request (and, on mlb-moneyline-forward-evidence, workflow_run) triggers removed;
only workflow_dispatch remains. No source module is deleted and no collector was run.
Guard: `tests/test_dk_api_scheduled_workflow_guard_20261023.py`. Proposal branch
grok/t250-dk-api-guard-20261023; merging stays with the owner.
