# NFL Props — Part 2B Preregistration (frozen 2026-10-20)

Status: FROZEN — IN FORCE on commit, 2026-10-20. Authored 2026-10-19 by
Rocky (main-chat agent) from the terms Isaac already ruled and recorded,
because the earlier Part 2B draft text exists nowhere reachable: it is not
in the repository and not in the current Claude session (it lived in an
earlier session instance). Isaac ruled on the §6 open items on 2026-10-20:
item 1 is resolved as option (a) — no 2B-specific row floor beyond §4 —
and item 2 stands as the timing rule stated in §6. This document and the
code that implements it (research/nfl_props_part2b_20261020/) are
committed before the first slate priced under it. The frozen Part 2
preregistration
(`PREREG_NFL_PROPS_PART2_FORWARD_V1`, merged on main, PR #2396) is NOT edited
by this document; Part 2B is a separate versioned preregistration standing
beside it, per Isaac's version-scoring rule: every model version is scored
as it stood when it priced the games.

## 1. What is being tested

The same CALIBRATED_CANDIDATE NFL props construction that Part 2 froze
(per-player predictive distributions built from the player's own prior
same-season games, shrunk toward role-pool means, point-in-time inputs
only), extended to three additional counting markets that passed the
historical calibration screen on 2026-10-18/19:

- **RUSH ATTEMPTS** — IN.
- **PASS ATTEMPTS** — IN, with the warning in §3 written into this document.
- **COMPLETIONS** — IN, with the warning in §3 written into this document.
- **PASSING TOUCHDOWNS** — SHADOW-ONLY: priced and recorded on the record,
  labeled SHADOW in every output, never counted toward any verdict, sample
  threshold, or card eligibility.
- **INTERCEPTIONS** — OUT: not priced, not recorded as test rows under 2B.

The screen that admitted rush attempts / pass attempts / completions was a
calibration check (constructed lines against simple averages) — it earns
these markets a seat in the forward test and says nothing about beating
DraftKings. The forward test below is the only market test.

## 2. The forward test (prospective)

- **Universe:** every paired DraftKings main-line prop in the three IN
  markets, for every game on each NFL slate, captured BEFORE kickoff of
  that game, paired (both sides, same half-line), timestamps recorded.
  Captures are committed to the record before the corresponding games are
  priced. Passing-TD rows are captured and recorded the same way but
  flagged SHADOW at capture time.
- **Pricing:** the committed construction, run from committed code on
  committed inputs (nflverse player data, point-in-time: only games
  completed before the slate). Output per row: model probability for both
  sides, fair odds, EV vs the captured DK price — committed before kickoff.
- **Scoring:** after each slate, per row: outcome vs line, log loss and
  CRPS of the model's stated distribution against the de-vigged DK market
  probability, with confidence intervals clustered by game (Part 2's
  clustering rule, carried forward). CLV (no-vig) is the PRIMARY verdict
  basis and win/loss is secondary, per market (Part 2, carried forward).
- **Missing close:** a row with no readable two-sided close at the final
  pre-kickoff capture is CLV_MISSING — it stays in win/loss, is excluded
  from the CLV average, and is never backfilled from another time or
  source. The CLV_MISSING share is reported per market with every readout,
  and >20% CLV_MISSING in a market makes its CLV verdict
  INSUFFICIENT_CLOSE_DATA regardless of row count (Part 2 rule, carried
  forward verbatim).

## 3. The busiest-QB warning (binding, written in per Isaac's ruling)

The historical screen found the construction runs HIGH for the busiest
quarterbacks on volume stats: pass attempts and completions are
over-predicted for high-volume QBs — the same passing-level bias measured
in the Part 1/2 reproduction (passing-yards means ~10 yards too high)
surfacing in volume stats. Consequences inside this test:

- Pass-attempts and completions rows for high-volume QBs carry this warning
  on the run record; the warning is an annotation, not an adjustment — the
  construction as committed is not modified to chase it.
- **QB-clustered sensitivity analysis (new in 2B):** in addition to the
  game-clustered intervals in §2, every readout for PASS ATTEMPTS and
  COMPLETIONS also reports the same verdict statistics with intervals
  clustered by QB. If the game-clustered and QB-clustered reads disagree
  on a verdict, the market's verdict is reported as the WEAKER of the two
  reads with the disagreement stated — a verdict may not rest on treating
  one busy QB's repeated rows as independent evidence.

## 4. Sample size and verdict gates (Part 2 gates carried forward)

- No verdict review before **4 full slates AND exactly 40 distinct games
  per market** (Part 2's exact-number rule carried forward: every threshold
  in this document is an exact number, no approximations).
- Any market under **100 rows** stays INSUFFICIENT_SAMPLE.
- Verdicts are per market. Available labels: BEATS_MARKET /
  DOES_NOT_BEAT_MARKET / CALIBRATION_ONLY / INSUFFICIENT_SAMPLE /
  INSUFFICIENT_CLOSE_DATA. No label creates a PLAY; PLAY stays closed
  until Isaac rules on a completed verdict.
- SHADOW passing-TD rows never count toward any threshold in this section.

## 5. Integrity bindings (carried forward from Part 2 §5, unchanged)

- Code, inputs, fitting rules, and this document: committed before pricing.
- Captures: paired, timestamped, pre-kickoff; a capture that misses kickoff
  is excluded and the exclusion is recorded.
- No retrospective additions: a row not committed before its game is
  history, filed with the published-card evidence if it was published,
  never in the prospective sample.
- Role news (inactives, depth-chart changes) is recorded alongside each
  slate's rows as context. The construction as committed does not consume
  it; flags are annotations, not adjustments.
- The Part 2 four markets (passing yards, rushing yards, receiving yards,
  receptions) continue under the frozen Part 2 document; 2B neither
  restarts their sample nor changes their gates.

## 6. Owner rulings (recorded 2026-10-20)

1. **The 50-passing-yards-rows gate — RULED option (a) (Isaac,
   2026-10-20).** Part 2's Option C floor also requires 50 passing-yards
   rows before verdict review. That number is specific to a Part 2 market
   and does not transfer to 2B. There is NO 2B-specific row floor beyond
   §4's gates: no verdict review before 4 full slates AND exactly 40
   distinct games per market, and any market under 100 rows stays
   INSUFFICIENT_SAMPLE. §4 stands as written under this ruling; no added
   clause is inserted.

2. **First counted slate.** If this document and its code are committed
   before pricing on Thursday 2026-10-22 (Patriots @ Bears), that game is
   2B's first counted slate, alongside Part 2's. If the commit lands after
   Thursday pricing, the first counted slate is the next full slate after
   the commit — Thursday's expanded-market rows, if any are published,
   are then HISTORICAL RECORD only, never prospective 2B rows.

## 7. Provenance of the terms in this draft

- Markets in / shadow / out, the busiest-QB warning, and Thursday's lock
  list: Isaac's rulings of 2026-10-18, recorded in MEMORY.md and
  ~/memory/2026-10-18.md (lock list confirmed via relayed reply, Oct 18).
- New-versioned-document vehicle, carried-forward gates, QB-clustered
  sensitivity analysis: recorded 2026-10-19 in ~/memory/2026-10-19.md.
- Loss of the earlier draft and the Thursday four-market default if no
  fresh draft is committed in time: session report, 2026-10-19,
  ~/memory/2026-10-19.md.
