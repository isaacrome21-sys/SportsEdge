# SportsEdge Football Player / Roster / Matchup Context Stack

Status: implementation spec for CFB/NFL RUN IT context layer.

## Purpose
Add structured player, roster, depth, usage, scheme, injury-impact, and matchup context without contaminating SportsEdge Model_P or Truth Gate promotion evidence.

## Governance
- External grades, rankings, projections, and opinions are NOT Model_P.
- Official team availability/depth information has priority over third-party summaries.
- External quantitative/player sources may become model features only when an explicit versioned SportsEdge feature transform exists and is validated out of sample.
- Until then, every item is CONTEXT_ONLY and cannot independently create, promote, or boost a bet.
- Capper/editorial opinions never receive a vote.

## Source priority
### Availability / depth
1. Official team releases, depth charts, injury reports, transactions.
2. CFBDepth / TWO-DEEP / PFF / RotoWire where available.
3. Beat-writer confirmation and credible local reporting.

### Position and unit quality
- PFF
- 247Sports for CFB personnel/talent context
- ESPN positional/unit rankings
- Next Gen Stats for NFL
- Sports Info Solutions where publicly available

### Usage and snaps
- PFF
- RotoWire
- Sports Info Solutions
- Next Gen Stats

### Scheme and matchup
- PFF tendency/matchup data
- SIS Film Room/tendency data
- TWO-DEEP formation/depth views
- Betalytics as secondary context

### Injury impact
- Official status first
- Sports Info Solutions / SIC Score for severity and expected impact where available
- PFF/beat reporting for role replacement context

## Required per-game context record
For every serious RUN IT candidate, collect when available:
- QB1/QB2 status and expected starter
- OL starters, continuity, injuries, replacement level
- DL/pass-rush availability and rotation
- LB/secondary availability
- RB/WR/TE snap share and target/carry role changes
- key returners/suspensions/eligibility
- portal/transfers and depth attrition for CFB
- position-group strength
- pass protection vs pass rush mismatch
- run blocking vs front mismatch
- receiver separation/coverage matchup
- explosive-play creation/prevention
- red-zone personnel/tendencies
- third-down personnel/tendencies
- special-teams personnel changes when material
- source, capture timestamp, freshness, and confidence

## NFL-only extensions
- NGS separation / completion probability / pass-rush and blocking metrics
- personnel grouping and formation tendencies
- coverage-shell and man/zone matchup context
- pass-block/run-block win rate
- official referee-crew context where material

## CFB-only extensions
- recruiting/talent composite context
- portal gains/losses and returning production
- real-time depth-chart changes
- OL continuity and new-starter count
- QB experience / transfer transition

## Output rules
RUN IT should show only material context that could change a decision. Each item must be tagged as one of:
- VERIFIED_AVAILABILITY
- PLAYER_USAGE
- UNIT_STRENGTH
- SCHEME_MATCHUP
- INJURY_IMPACT
- DEPTH_PORTAL
- DATA_GAP

Every external item must also carry `model_p=false` unless it is produced by a validated SportsEdge model transform.

## Candidate escalation triggers
Reopen a frozen card only for:
- confirmed QB change
- starter scratch or major injury-status change
- material OL/secondary/pass-rush change
- unexpected snap/role change that meaningfully changes projection assumptions
- material scheme/formation change with verified evidence
- any other change already allowed by the CFB/NFL freeze-card protocol

## Anti-patterns
- Do not average PFF/SIS/NGS grades into a synthetic probability.
- Do not turn source agreement into confidence points.
- Do not promote a bet because multiple third-party sites like the same side.
- Do not let stale preseason depth charts override current official availability.
- Do not hide missing player-level data; emit DATA_GAP.
