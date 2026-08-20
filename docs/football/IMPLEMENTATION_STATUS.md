# Football Implementation Status

Status discipline: PRESENT != EXECUTED != EVIDENCE-PRODUCING.

## Current state

### PRESENT ON MAIN
- Full NFL/CFB declared market surface and per-market specifications.
- Four-layer state contract in the football spec.
- Positional target-share-over-expected x offensive usage interaction feature.
- Existing score-level football simulator and key-number PMF support.
- Contract tests for market-surface declaration and positional matchup features.

### NOT YET EXECUTED AS THE FULL FOOTBALL SYSTEM
- Engine A is not yet the required drive/play-level event simulator.
- Halves/quarters are not yet generated as partitions of the same simulated game path.
- Engine B player participation/usage is not yet assigning players on each simulated play.
- Engine C special-teams/situational event generation is not yet integrated into the same event stream.
- The full declared market grid is not yet being priced from a single shared simulation path.

### NOT YET PRODUCING PROMOTION EVIDENCE
- New football read-outs are NEW CHALLENGERS.
- No read-out inherits promotion from an older market.
- Promotion requires point-in-time validation and CLV evidence against a frozen incumbent.
- ROI is descriptive only; promotion is CLV-led because NFL/CFB samples are scarce.

## Sequencing gate

Do not treat Stage 4 simulator work as the next production priority until shared Stage 0 orchestration health is correct.

Stage 0 blockers that must be closed first:
1. An all-BLOCKED run must not report healthy/READY.
2. Acquisition must be able to distinguish ACQUISITION_MISSING from NOT_OFFERED and PROVIDER_UNSUPPORTED.
3. Evidence-journal / scheduled evidence accumulation must have an externally meaningful heartbeat; an Actions-only dead-man cannot detect Actions scheduling failure.
4. Shared state semantics must be used by MLB and football; do not create a second health-reporting path.

## First Engine A acceptance test after Stage 0

The first drive/play simulator acceptance test is path conservation, not betting accuracy:

For every simulated game path:
- Q1 + Q2 = first-half score for each team.
- Q3 + Q4 (+ OT when applicable) = second-half/remaining score under the market's settlement definition.
- first-half points + second-half/OT points = final game points.
- home final + away final = game total.
- home final - away final = game margin.

A half/quarter market may never be generated from an independent draw. If any partition fails to reconcile to the parent game path, Engine A is ENGINE_BLOCKED.
