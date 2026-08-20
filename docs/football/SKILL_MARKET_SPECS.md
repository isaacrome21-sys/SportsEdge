# SportsEdge Football — Skill-Player Market Specs

Engine B is mandatory for all player markets. Unresolved participation means `INPUT_MISSING`, never PASS. Defensive positional target-share-over-expected is crossed with the offense's WR/TE/RB target share before player-level allocation; player usage then determines which individual receives the opportunity.

## Rushing Yards
### 1. READ-OUT DEFINITION
For player p, `RY_i=sum(official rushing yards credited to p)` across valid rush plays on shared path i. A+B.
### 2. REQUIRED INPUTS
Active status/depth role (NFL official/free + team news, TTL 10m after inactive report; CFB mixed free/paid 30-60m, block if unresolved), snap share/rush share/red-zone share (paid tracking or free derived PBP, TTL 6h/30m game day, block), OL injuries and run efficiency (24h), opponent front/tackle efficiency (24h), score-script substitution/blowout hazard (24h; crucial CFB), weather/surface (60m), quote 30-90s.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-14%; G5/FCS 12-20%. `b=1.5pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Official rush yards, including losses; kneels only for credited player (usually QB), not RB. Nullified plays excluded; 2PT plays excluded from standard stats; OT by book. Inactive void per book; pregame unresolved => INPUT_MISSING.
### 5. VALIDATION PLAN
>=1,500 priceable opportunities, >=250 challenger bets; hierarchical by role/player/team and walk-forward. Calibrate distribution by expected attempts/game script; Brier/log loss/reliability and CLV.
### 6. STATE TRANSITIONS
PRICED only with A+B and resolved role; NO_ENGINE if player rush attribution absent; INPUT_MISSING if active/rush share uncertain beyond modeled threshold; ENGINE_BLOCKED on team/player rush reconciliation failure; BET/PASS afterward.
### 7. CORRELATION CLUSTER
`RUSH_TREE:<team>` + team offense; correlated with rush attempts, QB/RB competing rush share, spread, team total and rushing TDs.

## Receiving Yards
### 1. READ-OUT DEFINITION
`RecY_i=sum(official receiving yards credited to p on completed passes)`; the sum over receivers reconciles with passer output under official lateral rules. A+B.
### 2. REQUIRED INPUTS
Active/snap/route status, target share by personnel/game state, aDOT/YAC profile, QB identity, positional target-OE x team positional usage, opponent coverage/pressure, weather/wind, quote TTL. Unresolved route participation or QB blocks.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-14%; G5/FCS 12-20%. `b=1.5pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Official receiving yards; lateral attribution by official scorer; nullified/2PT plays excluded; OT per book; inactive void by book.
### 5. VALIDATION PLAN
>=1,500 opportunities, >=250 bets; role/position hierarchical calibration, PIT/reliability and CLV. CFB starter-pull paths must be validated separately in mismatch bins.
### 6. STATE TRANSITIONS
INPUT_MISSING if player/QB/route role unresolved; ENGINE_BLOCKED if receiving totals fail passer reconciliation; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE` + player target tree; correlated with targets, receptions, longest reception, QB pass yards, team total and TD props.

## Receptions
### 1. READ-OUT DEFINITION
`REC_i=count(completed passes officially credited as receptions to p)`. A+B.
### 2. REQUIRED INPUTS
Active/snap/route/target share, QB attempt/completion distribution, target-OE positional interaction, matchup coverage, weather. Role unresolved blocks.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-14%; G5/FCS 12-20%. `b=1.5pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Official receptions only; 2PT excluded; nullified plays excluded; OT per book.
### 5. VALIDATION PLAN
>=1,500 opportunities, >=250 bets; calibrate conditional on targets and catch probability; CLV primary.
### 6. STATE TRANSITIONS
INPUT_MISSING on unresolved route/target role; ENGINE_BLOCKED if receptions exceed targets or fail completion reconciliation; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE`; especially targets, receiving yards, QB completions and pass attempts.

## Rush Attempts
### 1. READ-OUT DEFINITION
`RA_i=count(official rushing attempts credited to p)`. Engine B allocates carries conditional on personnel, score and substitution state. A+B.
### 2. REQUIRED INPUTS
Active/depth status, snap share, rush share, short-yardage/red-zone role, team run rate by game state, competing backs/QB usage, CFB blowout substitution. Unresolved role blocks.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-14%; G5/FCS 12-20%. `b=1.5pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Official attempts; receptions/laterals not carries unless scorer credits rush; kneels credited to QB under official stats; 2PT excluded; OT per book.
### 5. VALIDATION PLAN
>=1,500 opportunities, >=250 bets. This is a promising Engine-B market because usage/news can move faster than prices; validate share distribution and CLV.
### 6. STATE TRANSITIONS
INPUT_MISSING if carry role unresolved; ENGINE_BLOCKED if player attempts do not sum to team attempts under attribution; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`RUSH_TREE`; correlated with rushing yards, game script/spread, competing back attempts and team total.

## Targets
### 1. READ-OUT DEFINITION
`TGT_i=count(valid pass attempts on which p is official/intended target under chosen data-provider definition)`. The simulator stores target identity before completion outcome. A+B.
### 2. REQUIRED INPUTS
Active/snap/route participation, target share by personnel/down/score, QB attempts, target-OE positional matchup interaction, coverage tendencies. Reliable target-stat settlement feed required; CFB public target data can be incomplete and may block validation/production.
### 3. HOLD AND THRESHOLD
NFL 7-12% when offered; P4 9-16%; G5/FCS 13-22%, often unavailable. `b=1.8pp, lambda=0.75, z=1.55`.
### 4. SETTLEMENT RULES
Targets are provider-defined and not an official NFL box-score stat in the same way as receptions; SportsEdge must bind to the sportsbook's stats provider. Throwaways, spikes and tipped passes need provider semantics. OT per book.
### 5. VALIDATION PLAN
>=1,500 opportunities, >=250 bets, but only within one settlement-provider definition. If CFB target feed is incomplete, market remains NO_ENGINE/ENGINE_BLOCKED for promotion despite theoretical read-out.
### 6. STATE TRANSITIONS
NO_ENGINE if trustworthy target attribution feed absent; INPUT_MISSING if route/target role unresolved; ENGINE_BLOCKED on provider-semantic mismatch; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE`; upstream of receptions/yards and strongly correlated with QB attempts.

## Rush + Receiving Yards
### 1. READ-OUT DEFINITION
`Y_i=RY_i+RecY_i` for the same player/path. A+B; no independent convolution.
### 2. REQUIRED INPUTS
Union of rushing and receiving requirements; dual-role usage split must be resolved. Unresolved participation blocks.
### 3. HOLD AND THRESHOLD
NFL 7-12%; P4 9-16%; G5/FCS 12-22%. `b=1.8pp, lambda=0.75, z=1.55`.
### 4. SETTLEMENT RULES
Sum official rushing + receiving yards; no return yards unless market explicitly includes them; 2PT excluded; OT per book.
### 5. VALIDATION PLAN
>=1,250 opportunities, >=200 bets. Validate joint path distribution and CLV; do not derive from independent marginal props.
### 6. STATE TRANSITIONS
NO_ENGINE if either component absent; INPUT_MISSING on unresolved usage split; ENGINE_BLOCKED on component reconciliation; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
Both `RUSH_TREE` and `QB_PASS_TREE`; highly correlated with the component props and team offense.

## Longest Reception
### 1. READ-OUT DEFINITION
`LR_i=max(yards on any official reception by p)` with 0/none if no reception. A+B.
### 2. REQUIRED INPUTS
Route participation, target depth, YAC/explosive profile, QB deep-pass distribution, opponent explosive allowance, positional target-OE interaction, wind/gust. Deep-route role unresolved blocks.
### 3. HOLD AND THRESHOLD
NFL 9-16%; P4 11-20%; G5/FCS 15-28%. `b=2.3pp, lambda=0.85, z=1.65`.
### 4. SETTLEMENT RULES
Official single-play receiving yards; lateral attribution per scorer; nullified/2PT excluded; OT per book.
### 5. VALIDATION PLAN
>=2,000 opportunities, >=250 bets; tail calibration needs multiple seasons. CLV primary.
### 6. STATE TRANSITIONS
INPUT_MISSING on route/deep-role uncertainty; ENGINE_BLOCKED if max reception not traceable to valid play; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`QB_PASS_TREE`; correlated with receiving yards, QB longest completion and explosive TD paths.

## Longest Rush
### 1. READ-OUT DEFINITION
`LRush_i=max(yards on official rush attempts by p)` with 0/none state. A+B.
### 2. REQUIRED INPUTS
Rush role, blocking/run concept, explosive-run distribution, defense fit/tackling, surface/weather, substitution/blowout state. Role unresolved blocks.
### 3. HOLD AND THRESHOLD
NFL 9-16%; P4 11-20%; G5/FCS 15-28%. `b=2.3pp, lambda=0.85, z=1.65`.
### 4. SETTLEMENT RULES
Official longest rush; kneels technically can be rushes but cannot set a positive longest if other rushes exist; nullified/2PT excluded; OT per book.
### 5. VALIDATION PLAN
>=2,000 opportunities, >=250 bets; tail/explosive calibration by role and CLV. Multiple seasons likely.
### 6. STATE TRANSITIONS
INPUT_MISSING on role uncertainty; ENGINE_BLOCKED if longest play does not reconcile to player rush log; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`RUSH_TREE`; correlated with rushing yards, attempts and explosive scoring paths.

## Anytime Touchdown
### 1. READ-OUT DEFINITION
For p, `ATD_i=1` if p scores >=1 TD on a rushing, receiving or eligible return TD event. Output component probabilities by TD type and combined union from the same path. A+B+C for return component.
### 2. REQUIRED INPUTS
Active/snap/route/rush/red-zone role, goal-line package, QB/team scoring distribution, return role if eligible, opponent red-zone/coverage/front, weather. Participation/red-zone role unresolved blocks.
### 3. HOLD AND THRESHOLD
NFL 10-18%; P4 12-22%; G5/FCS 15-30%. `b=2.5pp, lambda=0.90, z=1.65`; longshot prices may require even higher observed-hold floor.
### 4. SETTLEMENT RULES
Rushing/receiving/return TD inclusion must match book. Passing TD does not count as QB anytime TD unless QB personally rushes/receives/returns one. Fumble recovery TD depends market rules. 2PT conversions are not TDs. OT per book. Inactive void per book.
### 5. VALIDATION PLAN
>=2,000 priceable player-game opportunities and >=300 bets preferred; multiple seasons. Brier/log loss/reliability in low-probability buckets and CLV; ROI is noisy.
### 6. STATE TRANSITIONS
INPUT_MISSING if participation/red-zone role unresolved; NO_ENGINE if scorer identity not generated; ENGINE_BLOCKED if player TDs fail team TD/score reconciliation; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`TD_TREE:<team>` + team offense; very strong correlation with team total, pass/rush TD, teammate TDs, spread/game script and same player's yardage.

## First Touchdown
### 1. READ-OUT DEFINITION
Find first TD event in chronological path order; `p=P(first_TD_scorer=p)`, with no-TD and defensive/ST identities represented. A+B+C.
### 2. REQUIRED INPUTS
All anytime-TD inputs plus opening-drive sequencing, first-drive personnel, kickoff/possession, and return roles. Participation unresolved blocks.
### 3. HOLD AND THRESHOLD
NFL 18-30%; P4 20-35%; G5/FCS 25-45%. `b=4.0pp, lambda=1.00, z=1.80`. This market should overwhelmingly PASS.
### 4. SETTLEMENT RULES
First touchdown, not first score unless wording says so. Defensive/ST TD can precede offensive TD and may be included/excluded by market pool. 2PT not TD. Inactive void per book.
### 5. VALIDATION PLAN
>=5,000 priceable player opportunities and >=300 bets; several seasons likely. Multinomial calibration/sum-to-one audit, low-probability reliability and CLV.
### 6. STATE TRANSITIONS
NO_ENGINE if ordered scorer identity absent; INPUT_MISSING on any candidate player's unresolved role that materially changes pool normalization; ENGINE_BLOCKED if scorer probabilities fail exhaustive normalization; PRICED then usually PASS.
### 7. CORRELATION CLUSTER
Opening-drive + `TD_TREE`; all first-TD candidates are mutually exclusive pieces of one position and cannot be treated as independent tickets.

## 2+ Touchdowns
### 1. READ-OUT DEFINITION
`p=P(TD_count_p>=2)` from the same player TD event stream, with type components retained. A+B+C.
### 2. REQUIRED INPUTS
Same as anytime TD with stronger dependence on full-game snap persistence, blowout substitution and red-zone role. CFB mismatch starter-pull uncertainty is a major block.
### 3. HOLD AND THRESHOLD
NFL 14-25%; P4 16-28%; G5/FCS 20-38%. `b=3.5pp, lambda=0.95, z=1.75`.
### 4. SETTLEMENT RULES
At least two qualifying TDs under market scorer rules; 2PT excluded; OT per book; inactive void per book.
### 5. VALIDATION PLAN
>=3,000 priceable opportunities and >=250 bets; multi-season. Tail/count calibration and CLV; no ROI promotion.
### 6. STATE TRANSITIONS
INPUT_MISSING when role persistence/substitution uncertain; ENGINE_BLOCKED on TD count reconciliation; PRICED then usually PASS.
### 7. CORRELATION CLUSTER
`TD_TREE`; strongly correlated with anytime TD, team total, player volume and blowout game scripts.
