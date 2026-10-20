# NFL props Part 2B — freeze package report (2026-10-20)

**Purpose.** Make Part 2B freezable: audit the frozen Part 2 construction
against the three Part 2B markets, build only what the audit proved
missing, and commit the preregistration + implementing code before the
first slate priced under it (Thu 2026-10-22, Patriots @ Bears — see the
preregistration §6 item 2 timing rule).

## Step 1 — audit of the frozen Part 2 construction (evidence, not inference)

Frozen package: `research/nfl_props_part2_20261018/` on main
`07b46d38334453bac76ceecd017c593452384b5b`. The pricing runner
(`price_nfl_props_part2.py`) imports the Part 1 evaluator
(`eval_nfl_props_calibration_v1.py`, sha256 `66de5615…`, pinned) unchanged
and iterates `ev.MARKETS`.

Live run against the evaluator (real pinned snapshot, sandbox data dir):

- `MARKETS` = exactly `{PASS_YDS, RUSH_YDS, REC_YDS, RECEPTIONS}`.
- `load()` reads only 7 stat columns; the nflverse weekly files DO carry
  `completions` and `passing_tds` (verified in the file headers) but the
  frozen loader never reads them.
- A capture containing a `RUSH_ATTEMPTS` row makes the frozen runner
  raise `KeyError: 'RUSH_ATTEMPTS'`; a `PASS_YDS` row in the same harness
  prices normally (mu = 244.37).

**Verdict:** the construction cannot price RUSH ATTEMPTS, PASS ATTEMPTS,
or COMPLETIONS today — but this is an *extension* gap, not a new-model
gap. Every construction primitive is market-generic (shrunk mean
`mu_for` with K = 3, role qualification, pooled per-market CV from
2018–2019 training ratios, Poisson/NegBin count predictive — the path
RECEPTIONS already uses). The missing pieces are exactly: two loader
columns and the market configurations.

## Step 2 — what was built (this directory)

- `eval_nfl_props_part2b_v1.py` (sha256 `a941164e…`) — the Part 1
  evaluator copied verbatim; the ONLY differences are (a) `load()` also
  reads `completions` and `passing_tds`, (b) `MARKETS` names the 2B
  markets, (c) hash pins point at this package's SPEC_HASHES.txt,
  (d) `evaluate()` tags shadow markets in its result record. Verified by
  AST comparison: `qualified_rows`, `build`, `league_pool`, `mu_for`,
  `candidate_cdf`, `emp_cdf`, `crps`, `boot` are identical to Part 1.
  The Part 1 evaluator file is untouched (a test pins its hash).
- Market configurations — each reuses the role population of the frozen
  market whose volume it counts (no new thresholds):
  - `RUSH_ATTEMPTS`: stat `carries`, role `carries`, thr 8.0 (RUSH_YDS
    gate), count.
  - `PASS_ATTEMPTS`: stat `attempts`, role `attempts`, thr 20.0
    (PASS_YDS gate), QB only, count.
  - `COMPLETIONS`: stat `completions`, role `attempts`, thr 20.0, QB
    only, count.
  - `PASS_TDS` (SHADOW): stat `passing_tds`, role `attempts`, thr 20.0,
    QB only, count, `shadow: True`.
- `price_nfl_props_part2b.py` — the Part 2 runner mirrored, with: 2B
  pins; a fail-closed scope guard (`MARKET_OUT_OF_SCOPE_2B` — an
  INTERCEPTIONS row, OUT under §1, is refused, never priced); PASS_TDS
  rows priced and recorded with `label: "SHADOW"` on every row;
  priced PASS_ATTEMPTS/COMPLETIONS rows carry the §3 busiest-QB warning
  in a `warning` field (annotation only — every priced row in those two
  markets carries it, since only QBs qualify there and the prereg gives
  no numeric high-volume cutoff; no threshold was invented).
- `score_nfl_props_part2b.py` — the Part 2 scorer mirrored, with the 2B
  rules: verdict gates are §4 **as ruled 2026-10-20 (option (a))** — no
  market-specific row floor (the Part 2 scorer's 50-passing-yards-row
  condition does not exist here); CLV primary with game-clustered CIs;
  PASS_ATTEMPTS/COMPLETIONS also report QB-clustered CLV CIs and a
  disagreement between the two clusterings weakens the verdict to the
  weaker read (§3); SHADOW rows are scored onto the record only and
  never enter any aggregate, sample count, or verdict. (The Part 2
  scorer's #2388 under-rate tables are not carried over — they are a
  Part 2 prereg item, not a 2B one.)
- `SPEC_HASHES.txt` — the frozen 2B preregistration (sha256 `55e11a81…`)
  plus the same data-file pins as Part 2 (generated mechanically from
  Part 2's committed file; all pins verified against the snapshot).
- `test_nfl_props_part2b.py` — 18 tests mirroring the Part 2 categories
  (pins/construction identity, distribution sanity incl. the count
  floor rule, hand-checked mus, PIT exclusion, qualification gates,
  shadow labeling, interceptions refusal, close-attachment parity,
  verdict-gate order incl. the §6(a) no-floor rule, QB-disagreement
  weakening, shadow exclusion from aggregates, frozen-doc terms).

## Calibration consistency run (mechanics check, not new evidence)

`eval_nfl_props_part2b_v1.py` run end-to-end on the pinned snapshot
(2018–2025; trained 2018–2019; scored 2020–2025, weeks ≥ 4) — the same
vintage as the original screens, so this checks that the committed
extension reproduces the screen's premise; the forward test remains the
only market verdict path. Results file sha256 `16d07cf8…`:

| Market | n | CRPS: candidate / B1 / B2 | Δ vs B1 (95% CI) | Δ vs B2 (95% CI) | CV | Screen verdict |
|---|---|---|---|---|---|---|
| Rush attempts | 3,217 | 3.208 / 3.389 / 3.572 | −0.181 [−0.220, −0.140] | −0.363 [−0.407, −0.318] | 0.448 | CALIBRATED_CANDIDATE |
| Pass attempts | 2,360 | 5.303 / 5.754 / 5.423 | −0.451 [−0.539, −0.374] | −0.120 [−0.197, −0.046] | 0.295 | CALIBRATED_CANDIDATE |
| Completions | 2,360 | 3.744 / 4.066 / 3.893 | −0.323 [−0.392, −0.259] | −0.149 [−0.214, −0.091] | 0.312 | CALIBRATED_CANDIDATE |
| Passing TDs (SHADOW) | 2,360 | 0.627 / 0.687 / 0.645 | −0.060 [−0.072, −0.049] | −0.018 [−0.027, −0.010] | 0.823 | CALIBRATED_CANDIDATE |

Population cross-check: rush attempts n = 3,217 = the frozen RUSH_YDS
population; the three QB markets n = 2,360 = the frozen PASS_YDS
population — the role gates select exactly the populations designed.

## Tests

- 2B suite: **18 passed**.
- Frozen Part 2 suite, run alongside in the same worktree: **17 passed**
  (35 total) — the sibling package disturbs nothing frozen.

## Freeze state

- Preregistration: §6 item 1 recorded as ruled option (a) (Isaac,
  2026-10-20); item 2 retained as the timing rule; status line records
  the freeze. No other text differs from the 2026-10-19 draft.
- Branch `feat/nfl-props-part2b-freeze-20261020`, committed locally,
  **not pushed** (owner push after review, per the standing workflow).
- Thursday pricing note: the 2B runner, like Part 2's, requires the
  pinned ps_2018/ps_2019 training files in the player-data dir at
  pricing time and hash-records the season file it consumes.
