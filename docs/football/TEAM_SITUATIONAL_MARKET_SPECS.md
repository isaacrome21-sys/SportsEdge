# SportsEdge Football — Team / Situational Market Specs

All markets are read-outs of the shared A/B/C path set. Hold bands are working engineering defaults and must be refreshed from observed paired-book snapshots.

## First Score
### 1. READ-OUT DEFINITION
Traverse valid scoring events by game clock and drive order; price team-to-score-first and, when offered, score-type/scorer variants. Team first-score uses A+C; scorer identity uses A+B+C. Return TD, defensive TD, safety, FG and offensive TD are separately tagged.
### 2. REQUIRED INPUTS
Opening possession rules/coin-toss handling or neutral prior (free; game-day; degrade if unknown), offense/defense drive-start distributions (free/paid, 24h), QB/inactives (NFL official TTL 10m after ~90m pre-kick report; CFB 30-60m confidence-weighted), kicker status (same), weather/roof 60/30m, Engine B usage for player scorer variants (block if unresolved), quote TTL 30-90s.
### 3. HOLD AND THRESHOLD
Team first score: NFL 7-12%, P4 9-14%, G5/FCS 11-18%. Player/score-type variants often 12-25% NFL, 15-30% P4, 20-40% G5/FCS. Use `b=2.0pp, lambda=0.80, z=1.55` team; `b=3.0pp, lambda=0.90, z=1.65` scorer/type.
### 4. SETTLEMENT RULES
First valid score by book definition. Defensive/ST scores and safeties count unless explicitly excluded. A nullified play does not count. Player void/inactive rules are book-specific; player variants require explicit participation rule. Suspended games after a score generally retain result only if book rules say market action; otherwise flag disputed.
### 5. VALIDATION PLAN
>=600 team-first-score settlements; player variants >=1,000 quote opportunities with >=150 challenger bets likely requiring multiple seasons. Brier/log loss/reliability and CLV to comparable close.
### 6. STATE TRANSITIONS
Team variant PRICED with A+C; player variant INPUT_MISSING if participation unresolved; NO_ENGINE if score-event ordering/type absent; ENGINE_BLOCKED if score reconciliation fails; BET/PASS only after pricing.
### 7. CORRELATION CLUSTER
Opening-drive/game-scoring cluster. Strongly correlated with first-half total, race-to-N, team total, kicker markets and first-TD scorer. Multiple first-score tickets are one position.

## Largest Lead
### 1. READ-OUT DEFINITION
For side S on path i, `L_i=max_t(score_S(t)-score_opp(t))`. Price over/under line or band predicates from `L_i`. A+C.
### 2. REQUIRED INPUTS
Full scoring path with timestamps, pace, QB/injury state, weather/roof. No Engine B required for team market. Quote identity must specify side and line.
### 3. HOLD AND THRESHOLD
NFL 8-14%; P4 10-16%; G5/FCS 12-22%. `b=2.0pp, lambda=0.80, z=1.55`.
### 4. SETTLEMENT RULES
Include all official points through market's stated regulation/OT window. Lead is evaluated immediately after each valid scoring event. Suspended/shortened games follow book.
### 5. VALIDATION PLAN
>=500 settled largest-lead markets; limited availability makes 2+ seasons realistic. Validate full lead distribution and CLV.
### 6. STATE TRANSITIONS
NO_ENGINE if intermediate score path unavailable; INPUT_MISSING if line/rule missing; ENGINE_BLOCKED if timeline inconsistent; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`GAME_RESULT` and side offense cluster; highly correlated with spread, ML, winning margin and garbage-time player usage.

## Winning Margin Bands
### 1. READ-OUT DEFINITION
Final margin `M=H-A`; each band is `P(a<=M<=b)` or team-specific signed equivalent. A+C, same discrete margin PMF as spread.
### 2. REQUIRED INPUTS
Core spread inputs, key-number calibrated margin PMF, band boundaries and tie/OT semantics.
### 3. HOLD AND THRESHOLD
NFL 10-18%; P4 12-20%; G5/FCS 15-28%. `b=2.5pp, lambda=0.85, z=1.60`; very narrow/longshot bands may require higher configured base.
### 4. SETTLEMENT RULES
Full-game final margin under book OT rules. Exact band endpoints inclusive/exclusive per quote. Ties handled as own band/no-action if applicable.
### 5. VALIDATION PLAN
>=1,000 band quote opportunities across probability buckets and >=150 bets; multi-season likely. Enforce sum-to-one across exhaustive bands and calibrate bucket reliability.
### 6. STATE TRANSITIONS
PRICED if margin PMF exists; ENGINE_BLOCKED if band probabilities overlap/gap incorrectly or fail normalization; acquisition can be NOT_OFFERED per band; BET/PASS only on valid offered band.
### 7. CORRELATION CLUSTER
`GAME_RESULT`; all bands for one game are mutually exclusive pieces of the same position and cannot be staked independently.

## Both Teams to Score N
### 1. READ-OUT DEFINITION
For threshold N, `P(H_i>=N and A_i>=N)`; complement variants use exact Boolean predicates. A+C.
### 2. REQUIRED INPUTS
Full score distributions, QB/injury/weather inputs, threshold/rule identity. No B required.
### 3. HOLD AND THRESHOLD
NFL 8-14%; P4 10-16%; G5/FCS 12-22%. `b=2.0pp, lambda=0.80, z=1.55`.
### 4. SETTLEMENT RULES
All team points count unless market says offensive points only. OT inclusion explicit. Push generally impossible for Boolean threshold unless special line format.
### 5. VALIDATION PLAN
>=600 settled markets per N-band; 1-2 seasons depending availability. Reliability and CLV.
### 6. STATE TRANSITIONS
PRICED with team score pair distribution; INPUT_MISSING for rule/N ambiguity; ENGINE_BLOCKED on score mismatch; BET/PASS after gate.
### 7. CORRELATION CLUSTER
`GAME_SCORING`; correlated with total, both team totals, passing/rushing TDs and anytime TD markets.

## Total Touchdowns
### 1. READ-OUT DEFINITION
Count touchdown events on path: offensive rushing, receiving, return and defensive TDs, with 2PT/XP excluded. `TD_i=sum(credited TD events)`; price over/under or exact count. A; B for scorer attribution but not team aggregate; C for return TD events.
### 2. REQUIRED INPUTS
Red-zone/TD event model, turnover-return model, special-teams return model, QB/injuries/weather. If market excludes defensive/ST TDs, explicit rule mapping required.
### 3. HOLD AND THRESHOLD
NFL 7-12%; P4 9-15%; G5/FCS 11-20%. Exact-count variants 10-20%+; `b=1.8pp, lambda=0.75, z=1.50` O/U, higher `b=2.5pp` exact/longshot.
### 4. SETTLEMENT RULES
TD = six-point touchdown event only; 2PT conversions are not TDs for stats markets unless book explicitly says scoring plays. Defensive/ST TD inclusion per market. OT per book.
### 5. VALIDATION PLAN
>=600 O/U settlements or >=1,000 exact-count opportunities. Score distribution calibration and CLV; likely 1-2 seasons.
### 6. STATE TRANSITIONS
NO_ENGINE if TD event types not explicit; ENGINE_BLOCKED if TD count fails score reconciliation; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`GAME_SCORING` + both `TD_TREE`s; tightly correlated with total, team totals, pass TDs and scorer props.

## Longest Field Goal Made
### 1. READ-OUT DEFINITION
For every FG attempt generated by A and resolved by C, record made distance. `LFG_i=max(distance_j for made FG_j)`, with 0/none state. Price over/under or bands. A+C.
### 2. REQUIRED INPUTS
Kicker identity/status and distance curve (free basic/paid tracking; TTL 24h, game-day status 10-30m), stadium altitude/surface static, kickoff wind/gust/roof 30-60m, coaching FG decision tendencies 7d, field position/drive model, quote TTL 30-90s. Unresolved kicker or roof/wind state with material impact blocks.
### 3. HOLD AND THRESHOLD
NFL 10-18%; P4 12-22%; G5/FCS 15-28% and often not offered. `b=2.5pp, lambda=0.90, z=1.65`.
### 4. SETTLEMENT RULES
Only made FGs count. Distance follows official scoring. No made FG => book-specific under/zero semantics. OT included if full-game. Nullified kicks excluded.
### 5. VALIDATION PLAN
>=750 quote opportunities and >=125 bets; 2+ seasons likely. Calibrate kicker distance bins and conditional attempt/make distributions; CLV primary.
### 6. STATE TRANSITIONS
INPUT_MISSING for unresolved kicker or material roof/wind; NO_ENGINE if C distance-specific FG engine absent; ENGINE_BLOCKED if FG attempts do not reconcile to scoring; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
`KICK_TREE` and game scoring; correlated with team total, spread, red-zone failure, FG made and kicking points.

## Defensive / Special-Teams Touchdown
### 1. READ-OUT DEFINITION
Boolean/count event from tagged interception-return, fumble-return, blocked-kick/return, kickoff/punt return TD paths. `p=P(DST_TD_i>=1)`. A+C; defender identity not needed for team DST market.
### 2. REQUIRED INPUTS
Turnover rates and return-TD conditional model, pressure/sack-fumble rates, return-unit quality, kickoff/punt outcomes, QB ball-security, weather. Basic sources free; richer tracking paid. TTL 24h, injuries 10-60m. Can degrade for non-key returner absence if uncertainty inflated; unresolved returner/kicker only blocks if materially modeled.
### 3. HOLD AND THRESHOLD
NFL 12-22%; P4 15-25%; G5/FCS 18-32%. `b=3.0pp, lambda=0.95, z=1.70`.
### 4. SETTLEMENT RULES
Count only TD types included by book. PAT after a DST TD does not affect event. Offensive fumble recovery in end zone must be categorized correctly. OT per full-game rules.
### 5. VALIDATION PLAN
Rare event: >=2,000 priceable opportunities and >=200 bets is preferred; multiple seasons required. Brier/log loss especially important because event probabilities are low; reliability in low-probability buckets and CLV.
### 6. STATE TRANSITIONS
NO_ENGINE if return-TD event model absent; ENGINE_BLOCKED if event typing/reconciliation fails; INPUT_MISSING for market-rule ambiguity; PRICED then usually PASS unless very strong edge.
### 7. CORRELATION CLUSTER
`DEFENSE_TREE`, opponent QB turnover tree and game scoring. Positive DST-TD tickets correlate with opponent INT/turnover props and can negatively/positively affect offensive yardage scripts.

## Safety
### 1. READ-OUT DEFINITION
Boolean/count of valid two-point safety scoring events generated from field-position/down/play outcomes and special situations. `p=P(safety_count>=1)`. A+C.
### 2. REQUIRED INPUTS
Drive start/field position, sack/pressure, penalty/end-zone handling, punt/snap error components, QB mobility, weather/surface. Many rare-event components may require paid/event-level history; TTL 24h except injuries/weather. If safety mechanics are not explicitly represented, NO_ENGINE.
### 3. HOLD AND THRESHOLD
NFL 15-30%; P4 18-35%; G5/FCS 22-45% when offered. `b=4.0pp, lambda=1.00, z=1.80`. This should almost always PASS.
### 4. SETTLEMENT RULES
Use official two-point safety scoring; one-point conversion safeties are distinct and must follow book wording. Nullified plays excluded. OT included for full-game.
### 5. VALIDATION PLAN
Extremely rare: >=5,000 priceable game opportunities preferred; one or even several NFL seasons may be insufficient for stable tail validation. Use exact-event calibration, Bayesian shrinkage, log loss and CLV; no ROI promotion.
### 6. STATE TRANSITIONS
NO_ENGINE unless safety-generating mechanisms exist; INPUT_MISSING on ambiguous safety definition; ENGINE_BLOCKED on rule/event audit failure; PRICED then overwhelmingly PASS.
### 7. CORRELATION CLUSTER
Rare-event defense/special-teams cluster; correlated with sacks, field position, team turnovers and game total in nonlinear ways.
