# MLB batter doubleheader — Oct 19 blocked-row rerun (2026-10-27)

## What was blocked

The 2026-10-19 ALCS Game 6 run (Cleveland Guardians @ Tampa Bay Rays,
gamePk 849815; operative record `operative_run_20261019_mlb_alcs_g6/`,
board captured 2026-10-19 17:10 CT) submitted 170 starter batter rows.
**99 of them refused with `HISTORY_LEAK_OR_DUPLICATE_GAME`** — every row of
13 of the 18 starters (Steven Kwan, José Ramírez, Chase DeLauter, Jo Adell,
Nathaniel Lowe, Travis Bazzana, Patrick Bailey, Brayan Rocchio ×7 markets;
Yandy Díaz, Jonathan Aranda, Junior Caminero, Chandler Simpson,
Jonny DeLuca ×7–9 markets).

## Root cause (verified from code and live data)

The pre-fix prior-30-games window stamped each prior game at **date
midnight**. A legitimate doubleheader puts two distinct games on one date,
so their stamps collided and the bridge's timestamp-distinctness check read
them as one duplicated game and refused — fail-closed, but wrong.

Verified against live StatsAPI data: **each of the 13 blocked players has
exactly one real doubleheader date inside his prior-30 window** —
Cleveland players: 2026-09-04 (Detroit @ Cleveland, gamePks 824387 +
824424); Tampa Bay players: 2026-09-22 (two games). The 5 starters with no
doubleheader in window (Liam Hicks, Petey Halpin, Victor Mesa Jr.,
Richie Palacios, Taylor Walls) are exactly the 5 with zero blocked rows.
One-to-one correspondence; no other cause was present.

## The fix (already on main)

Commit `864f91c9` (2026-10-20) keyed duplicate detection on **game
identity**: the collector verifies each doubleheader gamePk's real start
from the schedule and returns `prior_game_ids` alongside the stamps; the
bridge refuses only when a gamePk repeats (a true duplicate, even under
two different stamps) or a prior start is not strictly before the source
as-of (the leak arm). Unverifiable doubleheader games are dropped, never
given invented times. This PR adds the missing real-data regression proof
and this rerun record; it changes no engine code and no threshold.

## Rerun method

`rerun_20261019_alcs_g6.py` (this directory) replicates the original
`price_batters.py` exactly — same board, same starter set, same fixture —
with `now` pinned to the original pregame instant (2026-10-19T22:10:00Z)
and the current main engine path (`phone_batter_rows`). StatsAPI game logs
for the completed 2026 season are final, so each player's prior-30 window
reproduces exactly. Per-player windows were independently re-derived and
checked: all 18 starters resolve to 30 prior games with **unique game
ids**, doubleheader dates as above.

## Rerun tally — the 99 previously blocked rows

All 99 matched a rerun output (none missing). **Zero** rows refuse with
`HISTORY_LEAK_OR_DUPLICATE_GAME` — in fact the code appears nowhere in the
full 170-row rerun.

| Outcome | Rows |
|---|---|
| Priced — WATCH_PRICE_CAP | 36 |
| Priced — WATCH_BELOW_EV_FLOOR | 31 |
| Priced — RESEARCH_CANDIDATE_NOT_VALIDATED | 19 |
| Still refuse — genuine reasons | 13 |

The 13 genuine refusals:

- **12 × `MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:NOT_RUN`** —
  one-sided milestone markets that by rule require a validated model.
  Unrelated to history; correctly still refused.
- **1 × `EMPIRICAL_DEGENERATE_TAIL_NO_VALIDATED_MODEL`** — the empirical
  prior-game proportion is exactly 0 or 1 for that market; no validated
  tail model exists. Correctly still refused.

No priced row used duplicated or leaked history: every priced row's
history window carries 30 distinct gamePks (identity-checked above), and
the bridge re-verifies id uniqueness and the leak arm on every call.

## Labels

Everything here is research-only. Nothing is promoted to validated, no
PLAY eligibility changes, no threshold was lowered, and the batter family
keeps its existing status. A genuine refusal above counts as a correct
outcome, not a failure of the fix.
