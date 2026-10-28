# SPEC — NFL live in-play: capture pilot V1 (no construction)

**Status: PILOT SPECIFICATION. This document designs a capture pilot
and nothing else.** There is no live construction, no live pricing,
no framework config for this family (declaring one would imply a
priced family; the framework is not offered a version to pin), and no
clock. Family before this pack: NO_CONSTRUCTION, with live/in-game
recorded OUT_OF_SCOPE in `docs/market_coverage_phase7.md`. The
owner's Oct 27, 2026 directive puts live in the taxonomy; this spec
is the family's first honest step — prove the data can be captured
before anyone designs a model that eats it. PAPER / research only.

## 1. Why capture comes first (and what "live" even means here)

Every other family in the program validates against a *pre-kickoff*
close — a price set with the same information the model had. A live
price is set with *more* information than any pregame object: the
game so far. A live construction therefore competes with a market
that reprices on every play, and its only possible edge sources are
speed, state-modeling the book's engine does coarsely (e.g. its
treatment of clock/possession/timeout states), and stale-quote
windows. None of those can even be *measured* until the program can
capture, with disciplined timestamps, what the book was quoting at a
known game state. The pilot measures the capture. It prices nothing.

**Scope:** in-play markets on the main board: moneyline, spread,
total, team totals, and second-half lines at halftime (2H is an
in-play price — assigned here from the period family, whose markets
are regulation-defined pregame objects). Player props in-play are
out of the pilot's scope (DK suspends and re-posts them
discontinuously; a later pilot revision may add them with their own
suspension discipline).

## 2. What gets captured — the snapshot contract

For each pilot game, a **snapshot** is one rendered-page read of the
in-play board recording, atomically:

- both prices for every in-scope market then offered (ML, spread,
  total, both team totals), with the line each price attaches to;
- **game state at the read:** quarter, game clock, score (both
  teams), possession, down & distance and ball position where the
  rendered page shows them, timeouts remaining where shown. *A quote
  without its game state is not a snapshot* — it is unusable for any
  future baseline, and the pilot counts it as a failed snapshot;
- **suspension state:** any in-scope market shown suspended is
  recorded as suspended (market, state, timestamp) — suspensions are
  data (they mark the windows where no baseline exists), never
  silently skipped;
- the five #2792 receipt timestamps, extended for in-play (§3).

**Snapshot triggers** (whichever fires first, per game): (a) the
pre-kickoff baseline — the game's FINAL pregame capture under the
standing lane cadence, linked by event id (the pilot does not
re-read it; it inherits it); (b) after every scoring play;
(c) at each quarter break and at halftime (including the 2H board as
posted at the break); (d) at each two-minute warning; (e) a
heartbeat every 5 minutes of game clock when no other trigger has
fired. Kickoff to final whistle only; nothing is captured after the
game is final, and nothing captured late is backdated to a trigger.

## 3. Receipt and latency discipline (extends #2792)

Each snapshot carries: (1) trigger time (the game event or clock
mark that called for the snapshot, with its game state); (2)
board-read time (when the rendered page was actually read — the
quote's own timestamp); (3) ingestion time (snapshot parsed and
state-verified); (4) durable-write time (committed to the repo);
(5) state-verification result (the game state in the snapshot
matches an independent state source — the live scoreboard feed the
context layer already reads — within one play; a mismatch marks the
snapshot `STATE_UNVERIFIED` and excludes it from pilot metrics
except the failure count).

**Latency budget:** read-to-write (2)→(4) must complete within 120
seconds for a snapshot to count as on-time. A snapshot whose board
read happens more than 60 seconds after its trigger is
`LIVE_CAPTURE_LATE` — recorded permanently (the #2792 rule: failures
are records, never deletions), excluded from the baseline-continuity
metric, and counted in the pilot report. If a scoring play occurs
between trigger and read, the snapshot is attributed to the state at
its **read** time, never to the trigger's state — back-attribution
is the live-data version of backfilling and is prohibited in the
same words the frozen families use for closes.

## 4. The closing baseline for in-play (definition, fixed in advance)

A future live test will need a "close" per entry. It is defined now,
before any construction exists to benefit from a convenient choice:

- An in-play **entry** is a snapshot at a declared decision point
  (a trigger of §2) for a market that remains offered for the rest
  of the game (full-game ML/spread/total/team totals).
- The entry's **closing baseline** is the **last complete snapshot
  before the market's final suspension at game end** — the in-play
  analogue of the pre-kickoff close: the market's final word, set
  with nearly complete information. Live CLV for a future row =
  no-vig probability at that final snapshot − no-vig probability at
  the entry snapshot, **at the same line**; if the final snapshot's
  line differs, the row is the in-play analogue of LINE_MOVED and is
  bucketed separately under the v1.1 moved-row rules.
- Snapshots at intermediate triggers are the entry opportunities;
  they are never baselines for each other. Halftime 2H entries close
  against the same final snapshot rule.
- A game whose final snapshot is missing or `STATE_UNVERIFIED` has
  no baselines; its entries (in a future test) are CLV_MISSING with
  reason `NO_FINAL_SNAPSHOT`. The pilot's job is to make that reason
  rare and measured.

## 5. Pilot shape and success criteria

- **Scope of the pilot:** one primetime game per week (SNF or MNF)
  for **4 consecutive weeks**, run by the lines lane as a special
  task alongside (never instead of) the standing cadence; pilot
  games' pregame writes are unaffected.
- **The pilot passes iff, over the 4 games:** ≥ 95% of trigger
  snapshots land complete (all in-scope markets + verified game
  state + all five receipts); ≥ 99% of landed snapshots carry a
  verified game state; median read-to-write latency ≤ 60 seconds
  and p90 ≤ 120 seconds; every failure is recorded with its reason
  (no silent gaps — a missing snapshot with no failure record is
  itself a pilot failure, per the #2792 contract's spirit).
- **The pilot report** publishes: per-game trigger/snapshot/failure
  counts by trigger type and reason; latency distributions;
  suspension frequency by market and game state (the first honest
  map of when DK's live board is actually open); and the
  baseline-continuity rate (share of triggers whose market lines
  persist unchanged to the next snapshot — the raw material any
  future live CLV definition will stand on).
- **What a pass buys:** the right to *design* a live construction
  (state-conditioned, against the §4 baseline) and write its
  preregistration draft. What a fail buys: a recorded infrastructure
  gap and a pilot revision — not a quieter standard. The success
  criteria above are not lowered retroactively; a revised pilot is
  a new spec version with its own criteria, stated before it runs.

## 6. Explicit non-goals

No live picks, no live card rows, no in-play grading, no latency
arbitrage claims, no use of the DK API (rendered pages only, the
standing lane discipline), no signing into any account. Pilot data
is infrastructure evidence; it is not a backtest, and no construction
may be screened on it as if it were one (4 primetime games are a
capture sample, not a market sample). Same-game parlay in-play
quotes are out of scope until both the SGP family's capture pilot
and this one have reported.

*Spec prepared Oct 27–28, 2026 (activation pack). The pilot is lane
work, scheduled by the owner/lane; this document starts nothing.*
