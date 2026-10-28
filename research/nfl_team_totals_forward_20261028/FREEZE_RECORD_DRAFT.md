# FREEZE RECORD (DRAFT — NOT EXECUTED) — NFL Team Totals Forward Test V1

**Status: DRAFT RECORD. The freeze has NOT been recorded. Nothing in
this package is FROZEN, no clock has started, and no slate counts.**
This record is prepared for Rocky's exact-head independent review; the
freeze act itself (owner ruling + status flips + this record finalized
without the DRAFT marks) happens only after his clearance, per the
preregistration's §12 checklist. Prepared Oct 28, 2026.

- Document: `research/nfl_team_totals_forward_20261028/PREREG_NFL_TEAM_TOTALS_FORWARD_V1_DRAFT.md`
- This package's draft preregistration sha256:
  `c2f7f0934b52a8a3c6955692abe19d0312297ffd69701c2819c105755a24e224`
- Design origin: NFL activation pack, draft PR #2852
  (`research/nfl_activation_20261027/` — DESIGN + prereg draft + screen).

## Pins (sha256)

| Artifact | sha256 |
|---|---|
| Engine `sportsedge/nfl_team_total_dist.py` | `50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27` |
| Framework config `sportsedge/forward_validation/configs/nfl_team_total.json` | `6e468c6ab14a96c642cdcb4b42bd49cbb714f63e0ec13c4f04b669d477d3ba60` |
| Preregistration draft (this package) | `c2f7f0934b52a8a3c6955692abe19d0312297ffd69701c2819c105755a24e224` |
| Reproduction harness `reproduce_screen_with_engine.py` | see `SPEC_HASHES.txt` |
| Full pin list | `SPEC_HASHES.txt` in this package |

The config's `model_version` is the pin string
`nfl_team_total_dist_v1@sha256:50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27`:
any change to the engine file breaks the pin (and the binding test in
`tests/test_nfl_team_total_dist.py`) until the pin is re-struck. The
config's status remains `DRAFT — NOT FROZEN` until the freeze act.

## Construction identity

`NFL_TEAM_TOTAL_DIST_V1`: point-in-time shrunk offensive × defensive
team means over a negative-binomial law — same-season prior games
supplemented by prior-season games to 8, league pool mean G, K = 3
shrinkage, μ_T = off_T · def_O / G, NB with variance (c·μ_T)², c =
0.46438741207903494 from the 2018–2019 training seasons only. **Zero
market input** — no spread, total, or line enters any feature or the
probability path. Explicitly **not** a resurrection of the retired
NFL_ANCHORED_RATINGS_V1 (market-anchored, FAILED_SCREEN, stays
retired): this construction's only contact with the market is as the
baseline its forward test must beat.

## Screen evidence (design screen, reproduced with the built engine)

Design screen (activation pack, criteria fixed before the run):
**PASS** vs the point-in-time naive baselines — pooled MAE 7.749 vs
B1 7.831 / B2 7.924; pooled CRPS 5.528 vs 5.590 / 5.625; n = 3,230
team-games, 2020–2025; PIT mean 0.537; 91.0% inside the central 90%
band.

Reproduction with the built engine (this package,
`SCREEN_REPRODUCTION.md` + `screen_reproduction_results.json`): the
nflverse pull was byte-identical to the design pull (sha256
`1b4ca0c7…`), and **every number reproduced with delta exactly 0.0**,
including the training constant c. Screen verdict under the
pre-committed criteria: **PASS**, as designed. No tuning was performed
or needed; had the built engine not reproduced the screen, this
package would have stopped and reported instead.

### The disclosure that travels with the pass (verbatim from the design)

**Disclosure, in the open (the NBA team-totals §0 pattern):** the
candidate beats the naive baselines it was screened against — narrowly
(≈0.08 MAE pooled) — and **loses clearly to the market's implied split**
(7.749 vs 7.250). The forward test's governing leg is accuracy against
the DraftKings closing team-total line, and on this design evidence
that leg is the expected-risk leg: the DK team-total line is not a
naive (total ∓ spread)/2 split of a stale total — it is a traded line
informed by the closing spread and total, which are themselves sharp.
The construction advances to ARMED-pending-freeze because the screen it
was given asked about the naive baselines and it passed, and because
the forward test — not this screen — is where the market question is
answered, with the moved-row and CLV legs measuring something MAE
against a snapshot cannot. Anyone reading this pass as market evidence
is misreading it.

## Forward-test terms (from the preregistration draft, copied terms)

- **Governing leg §6a — accuracy vs close:** paired per-row ΔMAE of
  the engine mean vs the DraftKings closing team-total line; the §9
  interval's upper bound must lie below 0.
- **§6b — accuracy vs the existing model (Lane A):** the engine's mean
  must beat Lane A's emitted mean for the same team-game (Lane A
  hash-pinned at freeze; its emitted means recorded in the run
  record), same interval rule. This is the Oct 27, 2026 validation
  law's second baseline.
- **§6c — CLV:** mean CLV on PICKED rows > 0 (interval lower bound
  above 0) AND picked mean CLV > passed mean CLV, on rows whose valid
  close is at the entry line.
- **§6d — hit rate vs the market** on PICKED rows at the entry line.
- **Moved-row rules (NFL props v1.1):** checked first, in order —
  (1) adverse-vs-favorable moved PICKED rows significant at α/k in the
  adverse direction (one-sided exact sign test) → DOES_NOT_BEAT_MARKET
  regardless of §6a–§6d; (2) else moved PICKED rows > 50% →
  INSUFFICIENT_CLOSE_DATA. Zero moved picked rows: the sign test is
  not run and rule 1 does not apply. >20% of rows without a valid
  close → INSUFFICIENT_CLOSE_DATA.
- **Gates (minimums):** ≥4 full slates AND ≥150 engine-priced rows
  with valid close pairing AND ≥40 distinct games AND ≥50 picked
  rows. **The verdict review happens once**, at the first slate close
  where all gates are met; no interim looks at the primary metrics.
- **Pick rule (fixed):** gap = μ_T − entry_line; PICKED OVER if
  gap ≥ +2.0, PICKED UNDER if gap ≤ −2.0, else PASSED.
- **Intervals:** game-cluster bootstrap, 10,000 resamples, two-sided
  at level 1 − α/k, α = 0.05. **Bootstrap seed proposed: 20261028**
  (to be confirmed and recorded at the freeze act).
- A BEATS_MARKET verdict is this family's pass under the Oct 27, 2026
  validation law; it changes no registration or eligibility by itself,
  and no verdict under this test creates a PLAY.

## First counted slate

**The first slate priced after the pin lands** — i.e., the first NFL
slate priced after the freeze commit (this package, with status flips)
lands on main. Named by that date rule at the freeze act; **no
backfill**: rows priced before the freeze are historical record, never
prospective entries, and no §6 primary metric is computed on any
forward row before the first counted slate.

## α = 0.05/k — k counted as of this package (PROVISIONAL)

Per preregistration §9, k = the number of families validated or under
active forward test in the program whose windows overlap this test's
window, counting this test from its freeze date; the list is recorded
at freeze and again at review, and the larger k is used. Provisional
count at package preparation (Oct 28, 2026), resolved conservatively
in the NBA team-totals freeze record's manner (a clock that is frozen,
locked, or ruled to run and may count rows during this window is
included even if its own counting has not started):

| # | Clock | State at Oct 28, 2026 |
|---|---|---|
| 1 | NFL_PROPS_PART2_FORWARD_V1 | frozen, running |
| 2 | NFL_PROPS_PART2B_FORWARD_V1 | frozen, running |
| 3 | NFL_PROPS_V1_1_MOVED_LINE_AMENDMENT | counted separately, conservatively (as in the NBA team-totals freeze record) |
| 4 | NBA_PROPS_FORWARD_V1 | frozen clock (per the NBA team-totals freeze record) |
| 5 | NFL_TOTALS_LEVEL_V2_FORWARD | forward leg scores Jan 13, 2027 — window overlaps |
| 6 | MLB_PITCHER_PROP_PROMOTION_V2 (pitcher-K) | forward clock running |
| 7 | NFL_ANYTIME_TD_FORWARD_V1 (v1.1 terms) | frozen; accrual from Nov 1, 2026 slates |
| 8 | NFL_PASSYDS_V2_FORWARD_SCREEN | forward screen; population opens Oct 29, 2026 |
| 9 | NBA_TEAM_TOTALS_FORWARD_V1 | frozen Oct 22–23, 2026; counting pending the receipt act + eligibility |
| 10 | NFL_TEAM_TOTAL_DIST_V1 forward test | this test, from its freeze |

**Provisional k = 10 → α/k = 0.005; intervals two-sided at 99.5%.**
Excluded, with reasons: NBA_PROPS_V2 — its recorded freeze was
quarantined by owner ruling (Oct 27, 2026: the freeze does not
establish a valid clock start); it has no active clock. All DRAFT
families — not frozen, no clock. **The binding k is recorded at the
freeze act** and re-recorded at review; if the two differ, the larger
governs.

## Adaptation log (vs the #2852 activation pack)

- Framework config brought from the #2852 branch into this package at
  a pinnable state: `model_version` `nfl_team_total_dist_v1@UNPINNED`
  → the pin string above; `prereg_draft` repointed from the activation
  pack path to this package's preregistration (the document the config
  freezes with); `picked_beats_passed_required: true` added so the
  framework's verdict mode matches preregistration §6c (picked mean
  CLV must exceed passed mean CLV); formatting matched to the repo's
  config template. All other config values are the branch's verbatim
  (gates 150 rows / 40 events / 4 slates; close rule 60 minutes;
  CLV-missing cap 0.20).
- Preregistration text: the activation pack draft verbatim except the
  provenance lines, the framework-config pin, and the §1 engine pin.
  §0's implied-split disclosure is unaltered.
- The design screen's period-lines construction (NFL_PERIOD_SHARE_V1)
  recorded FAILED_SCREEN in the pack and is **not** part of this
  package; nothing here resurrects or retunes it.

## Freeze checklist status (preregistration §12)

- [x] Engine build of `NFL_TEAM_TOTAL_DIST_V1` committed with the
      hash-pin discipline (this package; builder-reported).
- [ ] Independently reviewed — CLEARED by a checker who did not build
      it (**Rocky's exact-head review; the freeze act waits on it**).
- [ ] Lane A's emitted-means recording verified in the run record
      (§6b depends on it).
- [ ] Bootstrap seed and the §9 k list recorded at the freeze act
      (proposals in this record: seed 20261028, provisional k = 10).
- [ ] This document frozen by owner ruling; the freeze record names
      the first counted slate as **the first slate priced after the
      engine pin is reviewed**. No primary metrics (§6) are computed
      on forward rows before then.

*Draft record prepared Oct 28, 2026. Not frozen. No clock started.*
