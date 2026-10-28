# MLB live (in-play) — pilot specification

**Status: PILOT SPEC — design only. Shadow mode: the pilot prices nothing
for any card, starts no clock, and creates no plays.** Live is the last
MLB frontier because its baseline problem is the hardest in the program: a
live price is only meaningful against the live market at the same game
state and the same moment, and SportsEdge has no in-play capture at all
today (the lane is pregame T-1H/FINAL only).

## What the pilot is for

To learn, on recorded evidence, whether a state-conditioned in-play model
can beat the live market at matched states — before anyone proposes a
construction, a preregistration, or a card role for live MLB.

## Pilot construction (the thing being piloted)

State = (inning, half, outs, base state, score differential, batting
team's lineup slot, current pitcher's workload state from design #1's
chain, bullpen availability state). From each state:

- Run-expectancy transition matrix (RE24 family) fit on StatsAPI
  play-by-play, strictly prior seasons (2023–2025 fit; 2026 as the
  design-check season — all DESIGN data).
- Remaining-game run distributions by Markov propagation over half-inning
  states, producing live win probability and live total/team-total
  distributions.
- The repo's inning score-path research (mlb_m21/m22/m50, score-path
  evidence dirs) is prior art to reuse for state-transition estimates,
  labeled with its recorded status; nothing in it is treated as validated.

## Capture design (infrastructure the pilot requires)

- A dedicated in-play capture (NEW scope; does not alter the pregame lane):
  for pilot games, snapshot DK's live moneyline and live total at each
  half-inning boundary, with the game state and a wall-clock timestamp
  recorded in the same receipt. Rendered pages only, same discipline as the
  pregame lane; five-timestamp receipts per #2792.
- Pilot slate: two games per week across April–May 2027 (chosen by a fixed
  rule — the first two DK-featured games each Monday — fixed here so the
  slate cannot be cherry-picked), plus every game of any series the
  pregame card priced, where feasible.
- Latency is a recorded variable, not an embarrassment: capture timestamp
  minus state-change timestamp is logged per snapshot; snapshots stale by
  more than 60 seconds are excluded from scoring and counted.

## Pilot scoring (fixed in advance; report, not verdict)

Per snapshot: model live win probability vs DK live no-vig probability —
Brier score and log loss, model vs market, paired by snapshot; live total
distribution vs DK live total — log loss on the realized remaining-runs
outcome bucketed to the offered line. The pilot report states the paired
differences with confidence intervals and the stale-snapshot rate. There
is NO pass/fail in the pilot: its output is a go/no-go recommendation for
drafting a live preregistration, decided by the owner on the report.
Promotion of any live construction requires its own preregistration and
the standard validation (chronological, vs the live market baseline and
the pregame model's state-0 projection carried forward as the "existing
model" comparator).

## Activation state on landing

PILOT SPEC only. Nothing runs until the in-play capture exists and the
owner schedules the pilot window. Pregame families are unaffected.

## Blockers

- In-play DK capture infrastructure does not exist (build owed; browser
  delivery acceptance under #2792 is itself still unproven pregame).
- Live DK pages during a game are the highest-latency surface the program
  touches; if the pilot's stale rate exceeds 25% of snapshots, the pilot
  reports capture-infeasible and stops — that outcome is a deliverable,
  not a failure to hide.
