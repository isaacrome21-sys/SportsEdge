# SportsEdge Football — Quarterback Market Specs

All QB markets are read-outs of the same A+B path set used by game markets. Player markets return `INPUT_MISSING` when participation is unresolved. NFL inactive information is re-snapshotted after official inactives roughly 90 minutes pre-kick; CFB uncertainty is materially worse and must be carried or block.

## Passing Yards
### 1. READ-OUT DEFINITION
For QB q on path i, `PY_i=sum(official passing yards credited to q on completed forward passes)`. Price over/push/under against line L. Receiver yardage on the same plays must reconcile to passing yardage under lateral/official-stat attribution. A+B.
### 2. REQUIRED INPUTS
QB active/start status (NFL official free TTL 10m after inactive list, block if unresolved; CFB team/news free/paid TTL 30-60m, block unless mixture defensible), projected snap/dropback share (paid tracking or derived PBP free, TTL 6h then 30m game day, block for player market), pass rate/pace/pressure matchup (free/paid 24h), receiver availability/target tree (same), positional target-share OE x offensive usage (free derived 24h, degrade if prior shrunk), weather/roof (free 60/30m, material wind blocks/degrades), quote 30-90s.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-14%; G5/FCS 12-20% where offered. `floor=b+lambda*max(0,h-h_ref)+z*SE`; `b=1.5pp, lambda=0.70, z=1.50`, higher for thin CFB books through observed hold and input SE.
### 4. SETTLEMENT RULES
Official passing yards; sacks not pass attempts/yards in NFL/college official stats; laterals follow official attribution; spikes are attempts/incompletions when officially scored; 2PT plays generally excluded from standard stats. OT included if book player-prop rules include it. If player inactive, void only per book rule; SportsEdge engine state remains INPUT_MISSING pregame when status unresolved. Shortened/suspended game by book.
### 5. VALIDATION PLAN
>=1,000 settled quote opportunities and >=200 challenger bets across walk-forward seasons; one QB/team has only 17/12 games, so hierarchical pooling is mandatory. Brier/log loss for O/U event, PIT/reliability, distribution calibration, and CLV to same-line/nearest comparable closing prop. Frozen incumbent is previous promoted QB-yard read-out, else market baseline.
### 6. STATE TRANSITIONS
PRICED only when A+B run and q participation resolved; NO_ENGINE if player pass attribution absent; INPUT_MISSING if start/snap/dropback share unresolved; ENGINE_BLOCKED on passing/receiving reconciliation failure; BET only after fixed decision chain; else PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE:<team>` + team offense. Strongly correlated with attempts, completions, pass TD, receiver targets/receptions/yards, team total and spread/game script. These are one position with many tickets.

## Completions
### 1. READ-OUT DEFINITION
`C_i=count(valid completed forward-pass attempts credited to q)`. O/U predicate on C_i. A+B.
### 2. REQUIRED INPUTS
QB participation, dropback/pass-attempt distribution, completion model by depth/pressure/personnel, receiver availability, wind/precipitation, quote TTL. Same block/degrade rules as passing yards.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-14%; G5/FCS 12-20%. `b=1.5pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Official completions. Spikes/incompletions not completions; sacks no attempt; accepted defensive penalty/no-play semantics follow official stat. 2PT plays excluded from standard stats. OT/book rules explicit.
### 5. VALIDATION PLAN
>=1,000 settled quote opportunities, >=200 bets; reliability by line/attempt bucket and CLV. Multiple seasons needed for role-specific claims.
### 6. STATE TRANSITIONS
INPUT_MISSING on unresolved QB role; ENGINE_BLOCKED if completion count fails attempt/receiver reconciliation; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE`; especially correlated with attempts, pass yards, receptions across receiver tree and negative game-script rush share.

## Attempts
### 1. READ-OUT DEFINITION
`ATT_i=count(official pass attempts by q)`. Generated directly from play-type decisions and QB participation, not a detached Poisson prop model. A+B.
### 2. REQUIRED INPUTS
QB active/snap share, pass rate over expected by game state, pace, opponent pressure, score-script response, weather, backup/substitution hazard. CFB mismatch/blowout substitution is critical and unresolved starter pull behavior can block promoted player pricing.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-14%; G5/FCS 12-20%. `b=1.5pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Official attempts; spikes count if official, sacks do not, scrambles do not, nullified plays excluded, 2PT excluded. OT per book.
### 5. VALIDATION PLAN
>=1,000 opportunities, >=200 bets. Validate attempt distribution by score-state and close-game/blowout bins; CLV primary.
### 6. STATE TRANSITIONS
INPUT_MISSING if starting/relief QB participation unresolved. ENGINE_BLOCKED if play-type totals/reconciliation fail. PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE`; attempts drive completions, yards, targets and often inversely relate to rush attempts depending script.

## Passing Touchdowns
### 1. READ-OUT DEFINITION
`PTD_i=count(offensive TD events credited as passing TD to q)`. Receiver TD identity comes from same play. A+B.
### 2. REQUIRED INPUTS
QB role, pass rate, red-zone pass rate, receiver red-zone participation/target share, defense coverage/pressure, weather, score script. Unresolved QB or red-zone receiver role blocks.
### 3. HOLD AND THRESHOLD
NFL 7-12%; P4 9-16%; G5/FCS 12-22%. `b=1.8pp, lambda=0.75, z=1.55`.
### 4. SETTLEMENT RULES
Official passing TDs; laterals after completed pass retain official passer TD only if official scoring credits it; 2PT passes are not passing TDs. OT per book.
### 5. VALIDATION PLAN
>=1,200 opportunities, >=200 bets; low-count distribution calibration, Brier/log loss by line and CLV. Multiple seasons for strong evidence.
### 6. STATE TRANSITIONS
INPUT_MISSING if QB/red-zone usage unresolved; ENGINE_BLOCKED if pass-TD and receiver-TD identities do not reconcile; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE` + `TD_TREE`; correlated with team total, receiver anytime TD, passing yards and total.

## Interceptions
### 1. READ-OUT DEFINITION
`INT_i=count(official interceptions thrown by q)` from pass-play turnover outcomes. Return yards/TD remain on same event. A+B.
### 2. REQUIRED INPUTS
QB status, attempt/depth profile, pressure/coverage matchup, turnover-worthy tendencies where available (paid/free derived, 7d), weather, offensive-line injuries. Participation unresolved blocks.
### 3. HOLD AND THRESHOLD
NFL 7-12%; P4 9-16%; G5/FCS 12-22%. `b=1.8pp, lambda=0.75, z=1.55`.
### 4. SETTLEMENT RULES
Official interceptions thrown; defensive penalties/no-play excluded; 2PT interceptions generally not standard INT stats; OT per book.
### 5. VALIDATION PLAN
>=1,200 opportunities, >=200 bets; rare-count reliability, calibration by attempt bucket, CLV.
### 6. STATE TRANSITIONS
INPUT_MISSING if QB role unresolved; ENGINE_BLOCKED if turnover event attribution fails; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE` + opponent `DEFENSE_TREE`; correlated with attempts, negative passing efficiency, team turnover, defensive TD and game script.

## QB Rush Yards
### 1. READ-OUT DEFINITION
`RY_i=sum(official rushing yards credited to q)`, separating designed runs, scrambles and kneels in event tags even when official market total includes all official rushing yards. A+B.
### 2. REQUIRED INPUTS
QB participation, designed-run share, scramble probability conditional on pressure/man coverage, sack escape, injury/mobility status, game script, surface/weather. NFL kneel expectation comes from win-state. CFB starter-pull risk is material.
### 3. HOLD AND THRESHOLD
NFL 7-12%; P4 9-16%; G5/FCS 12-22%. `b=1.8pp, lambda=0.75, z=1.55`.
### 4. SETTLEMENT RULES
Use official rushing yards including kneel-down effects if official stat/book does. Kneels must remain tagged so alternative provider semantics can be applied. Sacks are not QB rushes. 2PT rush excluded from standard stats. OT per book.
### 5. VALIDATION PLAN
>=1,000 opportunities, >=200 bets; separate designed-run/scramble/kneel calibration and CLV.
### 6. STATE TRANSITIONS
INPUT_MISSING on unresolved QB mobility/participation role; ENGINE_BLOCKED if sacks/scrambles/kneels are misclassified; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`RUSH_TREE` + `QB_PASS_TREE`; scramble yards can negatively correlate with completions but positively with pressure/drive continuation.

## Longest Completion
### 1. READ-OUT DEFINITION
For q on path i, `LC_i=max(yards_on_each_completed_pass credited to q)`, with zero/none state. A+B; same completion events as passing/receiving yards.
### 2. REQUIRED INPUTS
QB participation, target depth distribution, receiver route/deep-target role, YAC model, opponent explosive-pass allowance, wind/gust/roof. Deep receiver participation unresolved blocks.
### 3. HOLD AND THRESHOLD
NFL 9-16%; P4 11-20%; G5/FCS 15-28%. `b=2.3pp, lambda=0.85, z=1.65`.
### 4. SETTLEMENT RULES
Official completed-pass yardage; laterals follow official play-stat attribution; longest is maximum single credited completion. Nullified plays excluded, 2PT excluded, OT per book.
### 5. VALIDATION PLAN
>=1,500 quote opportunities and >=200 bets; tail calibration by air-yard/YAC bucket. Multiple seasons often needed. CLV primary.
### 6. STATE TRANSITIONS
INPUT_MISSING if QB/deep-target receiver role unresolved; ENGINE_BLOCKED if max completion not traceable to a valid completed play; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE`; highly correlated with receiver longest reception, passing yards and explosive scoring paths.

## Pass + Rush Yards
### 1. READ-OUT DEFINITION
`PRY_i=PY_i+RY_i` using official path-level passing and QB rushing totals from the same q. A+B.
### 2. REQUIRED INPUTS
Union of passing-yards and QB-rush inputs; QB participation is hard block. Weather and pressure influence both components.
### 3. HOLD AND THRESHOLD
NFL 7-12%; P4 9-16%; G5/FCS 12-22%. `b=1.8pp, lambda=0.75, z=1.55`.
### 4. SETTLEMENT RULES
Sum official pass yards + official rush yards under same game/OT rule; kneel effect follows official rush stats; 2PT excluded. Suspended game per book.
### 5. VALIDATION PLAN
>=1,000 opportunities, >=200 bets. Validate joint distribution, not marginal convolution; CLV against same combo market.
### 6. STATE TRANSITIONS
NO_ENGINE if either component cannot be produced from shared path; INPUT_MISSING if QB role unresolved; ENGINE_BLOCKED if component reconciliation fails; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
Combined `QB_PASS_TREE` + `RUSH_TREE`; also correlated with team total, spread/game script and receiver yardage.
