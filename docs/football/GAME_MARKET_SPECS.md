# SportsEdge Football — Game Market Specs

Engineering hold bands below are default configuration bands to be replaced/updated from SportsEdge's own observed paired-book snapshots. `A/B/C` refer to the shared engines in `FULL_MODEL_ORCHESTRATOR_SPEC.md`. Every probability is estimated from the same game-level simulation paths.

## Moneyline
### 1. READ-OUT DEFINITION
Let final score be `(H_i,A_i)` on path `i`. `p_home=P(H_i>A_i)`, `p_away=P(A_i>H_i)` with ties handled by competition/overtime rules. Depends on A; C is embedded insofar as kicking changes final score.
### 2. REQUIRED INPUTS
Team efficiency/PBP priors (free/paid alternatives; TTL 24h, degrade with shrinkage), starting QB/major injuries (NFL official+news free, TTL 10m after inactive report; CFB mixed free/paid, TTL 30-60m; unresolved QB blocks or explicit mixture), weather/roof (free, TTL 60/30m; degrade if low impact, block when material unresolved), surface/venue (free, season/static), paired prices (paid/free depending provider, TTL 30-90s; acquisition blocks decision but not engine). NFL inactives re-snap ~90m pre-kick.
### 3. HOLD AND THRESHOLD
Typical working hold bands: NFL 4-6%; CFB P4 4.5-7%; CFB G5/FCS 6-10%. Use `floor=b+lambda*max(0,h-h_ref)+z*SE_total`; default `b=1.0pp, lambda=0.50, z=1.28`, with `h_ref=4.5% NFL / 5.5% P4 / 7% G5-FCS`. Never lower floor because hold is high.
### 4. SETTLEMENT RULES
Include OT when sportsbook full-game ML includes OT. Tie/no-action follows book rules. Defensive/ST scores count because they change final score. Suspended/shortened game uses provider/book rule snapshot; if grading is ambiguous, settlement state is disputed and excluded from validation until resolved.
### 5. VALIDATION PLAN
Target >=500 settled priceable game opportunities across walk-forward seasons and >=100 challenger BET observations before strong promotion evidence; one NFL season has only 272 games, so one season cannot establish small ROI superiority. Score Brier/log loss/reliability and CLV versus frozen incumbent and consensus close. CLV is probability/price improvement to sharp close, not ROI.
### 6. STATE TRANSITIONS
PRICED when A completed with required QB/context mixture resolved; NO_ENGINE only if A absent; INPUT_MISSING when QB/game-status uncertainty cannot be represented; ENGINE_BLOCKED for failed reconciliation/calibration; BET only after full decision stack clears; otherwise PASS.
### 7. CORRELATION CLUSTER
`GAME_RESULT`, plus both offense scoring clusters. Strongly correlated with spread, team totals, total, margin bands and many player props. Multiple tickets are one exposure.

## Spread
### 1. READ-OUT DEFINITION
For home line `s`, `p_cover=P(H_i-A_i+s>0)`, `p_push=P(...=0)`. Read directly from discrete margin PMF; never smooth across 3, 7 or other point masses. A.
### 2. REQUIRED INPUTS
Same as ML plus validated discrete margin calibration/key-number profile (historical free/paid; frozen per season/week, block if missing for NFL promoted pricing). Market line/price TTL 30-90s.
### 3. HOLD AND THRESHOLD
NFL 4-5.5%; CFB P4 4.5-6.5%; G5/FCS 5.5-9%. `b=0.9pp, lambda=0.55, z=1.35`; key-number model uncertainty enters `SE_total` and rises if empirical PMF support is weak.
### 4. SETTLEMENT RULES
Full-game OT included when book includes it. Push exactly at integer line. Defensive/ST points count. Suspensions follow book. No rounding of simulated margin before grading.
### 5. VALIDATION PLAN
>=750 settled sides across walk-forward history preferred; >=150 challenger bets/quotes with CLV before promotion. One NFL season is only 272 sides, so multi-season evidence is mandatory for small improvements. Reliability by cover-probability bucket and separate calibration around 2.5/3/3.5 and 6.5/7/7.5.
### 6. STATE TRANSITIONS
INPUT_MISSING if key QB/major participation unresolved beyond modeled mixture or line identity incomplete. ENGINE_BLOCKED if key-number PMF/reconciliation fails. PRICED then BET/PASS only.
### 7. CORRELATION CLUSTER
`GAME_RESULT`; tightly linked to ML, margin bands, team totals, game total and offense/player scoring trees.

## Total
### 1. READ-OUT DEFINITION
`T_i=H_i+A_i`; for line `L`, over=`P(T_i>L)`, push=`P(T_i=L)`, under=`P(T_i<L)`. A with C scoring mechanics.
### 2. REQUIRED INPUTS
Team pace/efficiency, explosive rate, red-zone conversion, QB/injuries, weather/roof/surface, officiating if validated, all point-in-time; wind TTL 60m and materially affects pass/kick distributions. Quotes 30-90s. Missing weather may degrade only if dome/low sensitivity; material outdoor uncertainty blocks promoted pricing.
### 3. HOLD AND THRESHOLD
NFL 4-5.5%; P4 4.5-6.5%; G5/FCS 5.5-9%. `b=1.0pp, lambda=0.55, z=1.35`.
### 4. SETTLEMENT RULES
OT per book full-game total. All offensive, defensive and ST points count unless book explicitly defines otherwise. Push at exact integer total.
### 5. VALIDATION PLAN
>=750 settled totals preferred across seasons; >=150 challenger BET observations for promotion evidence. NFL closing totals are extremely sharp; CLV is primary. Validate total distribution tails and reliability by probability bucket.
### 6. STATE TRANSITIONS
PRICED if A/C score reconciliation passes; INPUT_MISSING for unresolved material QB/weather state; ENGINE_BLOCKED for clock/scoring invariant failure; BET/PASS after decision stack.
### 7. CORRELATION CLUSTER
`GAME_SCORING` and both offense clusters; correlated with team totals, QB/WR/RB yardage and TD props.

## Team Total
### 1. READ-OUT DEFINITION
For side `S`, `X_i=points_S(i)`; price `P(X_i>L)`, push, under. A+C.
### 2. REQUIRED INPUTS
All total inputs plus side-specific offensive/defensive matchup, QB and key skill availability. Player uncertainty can degrade game-level team total if represented as usage mixture. NFL inactive TTL 10m post-list; CFB uncertainty often 30-60m and may block.
### 3. HOLD AND THRESHOLD
NFL 5-8%; P4 6-9%; G5/FCS 8-12%. `b=1.25pp, lambda=0.60, z=1.40`.
### 4. SETTLEMENT RULES
All points credited to team count, including defensive/ST scores unless book says offensive-team-total. OT per book. Exact integer push.
### 5. VALIDATION PLAN
>=500 settled side-team totals across seasons; >=100 challenger bets. Effective sample lower because two team totals from one game are dependent. CLV vs same-market close.
### 6. STATE TRANSITIONS
INPUT_MISSING for unresolved QB/major offense role if no mixture; ENGINE_BLOCKED on score attribution failure; otherwise PRICED and BET/PASS.
### 7. CORRELATION CLUSTER
`GAME_SCORING` + side offense cluster; strongly correlated with spread, total, QB yards/TDs, receiver/rusher yards and TD scorer markets.

## First-Half Moneyline
### 1. READ-OUT DEFINITION
Use score after all valid first-half plays including untimed downs: `P(H_1H>A_1H)` etc. No separate sim. A+C.
### 2. REQUIRED INPUTS
Same game inputs plus first-half pace/script calibration; TTLs same as full game. Starting participation is especially critical; unresolved QB blocks.
### 3. HOLD AND THRESHOLD
NFL 5-8%; P4 6-9%; G5/FCS 8-12%. `b=1.3pp, lambda=0.60, z=1.40`.
### 4. SETTLEMENT RULES
No second-half/OT. First-half ties grade per market (draw/tie option or push/no-action). Defensive/ST points count.
### 5. VALIDATION PLAN
>=500 settled halves; >=100 challenger bets. One season can provide broad pooled signal but not team-specific validation. Brier/log loss/reliability and 1H closing CLV.
### 6. STATE TRANSITIONS
PRICED only if period slicing and clock invariants pass; INPUT_MISSING for unresolved starting QB; otherwise BET/PASS.
### 7. CORRELATION CLUSTER
`GAME_RESULT`, first-half subcluster; correlated with 1H spread/total and first-half player production.

## First-Half Spread
### 1. READ-OUT DEFINITION
`M_1H=H_1H-A_1H`; cover/push from discrete first-half margin PMF. A+C.
### 2. REQUIRED INPUTS
Full spread inputs plus first-half margin calibration. Weather/injuries same TTL. Key-number treatment remains discrete though 1H key masses differ from full game.
### 3. HOLD AND THRESHOLD
NFL 5-8%; P4 6-9%; G5/FCS 8-12%. `b=1.3pp, lambda=0.60, z=1.40`.
### 4. SETTLEMENT RULES
Only first half; no OT. Push at exact line; all first-half scoring counts.
### 5. VALIDATION PLAN
>=600 settled 1H spreads; >=100 challenger bets; calibrate margin buckets and CLV to 1H close.
### 6. STATE TRANSITIONS
ENGINE_BLOCKED if first-half state extraction is inconsistent; INPUT_MISSING for unresolved key participation; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
1H `GAME_RESULT`; strongly overlaps 1H ML/total and full-game result exposure.

## First-Half Total
### 1. READ-OUT DEFINITION
`T_1H=H_1H+A_1H`; over/push/under from first-half score slice. A+C.
### 2. REQUIRED INPUTS
Full total inputs plus first-half pace/end-of-half clock calibration. Wind/roof TTL as above.
### 3. HOLD AND THRESHOLD
NFL 5-8%; P4 6-9%; G5/FCS 8-12%. `b=1.3pp, lambda=0.60, z=1.40`.
### 4. SETTLEMENT RULES
Only first-half points including untimed downs; no OT.
### 5. VALIDATION PLAN
>=600 settled 1H totals; >=100 challenger bets. Reliability by total bucket; closing CLV primary.
### 6. STATE TRANSITIONS
ENGINE_BLOCKED on clock/end-of-half behavior failure; INPUT_MISSING for material QB/weather uncertainty; otherwise PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
1H scoring cluster; overlaps full total, team totals, first score and early player usage.

## Second-Half Moneyline
### 1. READ-OUT DEFINITION
For pregame offered 2H markets, isolate Q3+Q4 scoring differential, excluding first-half score; for live halftime markets initialize from actual halftime state then simulate remainder. A+C.
### 2. REQUIRED INPUTS
Pregame version uses base inputs; live version requires verified halftime state (free feed, TTL seconds, block if missing), current injuries/benching and live weather. Halftime participation updates TTL <=5m.
### 3. HOLD AND THRESHOLD
NFL 5-9%; P4 6-10%; G5/FCS 8-13%. `b=1.5pp, lambda=0.65, z=1.45`; live acquisition latency adds uncertainty.
### 4. SETTLEMENT RULES
Second-half scoring only. OT inclusion varies by book and must be encoded per provider; never assume. Tie rules per quote.
### 5. VALIDATION PLAN
>=500 settled 2H prices per settlement-rule class; live and pregame challengers are separate incumbents. CLV measured to final comparable 2H price, not full-game close.
### 6. STATE TRANSITIONS
INPUT_MISSING when halftime state/participation is unresolved; NO_ENGINE if no live-state initializer exists; ENGINE_BLOCKED on rule mismatch; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
2H result/scoring cluster; live versions strongly depend on same updated path and should share exposure with full-game live positions.

## Second-Half Spread
### 1. READ-OUT DEFINITION
Second-half-only margin `M_2H`; cover/push from discrete remainder/half PMF. A+C.
### 2. REQUIRED INPUTS
Same as 2H ML plus line-specific settlement rule and halftime state for live offering.
### 3. HOLD AND THRESHOLD
NFL 5-9%; P4 6-10%; G5/FCS 8-13%. `b=1.5pp, lambda=0.65, z=1.45`.
### 4. SETTLEMENT RULES
Grade only second-half score; OT only if provider rule says so. Push exact.
### 5. VALIDATION PLAN
>=500 settled 2H spreads; separate live/pre-game calibration; CLV to same market.
### 6. STATE TRANSITIONS
Same as 2H ML, with ENGINE_BLOCKED on missing discrete 2H margin support.
### 7. CORRELATION CLUSTER
2H result cluster; correlated with 2H total, live full-game spread and side offense trees.

## Second-Half Total
### 1. READ-OUT DEFINITION
Second-half-only points `T_2H`; over/push/under from shared remainder paths. A+C.
### 2. REQUIRED INPUTS
Halftime state, updated weather/participation for live; pregame uses base snapshot. Clock/pace halftime adjustments required.
### 3. HOLD AND THRESHOLD
NFL 5-9%; P4 6-10%; G5/FCS 8-13%. `b=1.5pp, lambda=0.65, z=1.45`.
### 4. SETTLEMENT RULES
Second-half points only; OT depends on book rule and must be explicit.
### 5. VALIDATION PLAN
>=500 settled; separate rule classes; Brier/log loss/reliability and comparable-market CLV.
### 6. STATE TRANSITIONS
INPUT_MISSING if verified halftime state unavailable; ENGINE_BLOCKED if pace/clock remainder model fails; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
2H scoring cluster and side offense clusters.

## Quarter Moneyline
### 1. READ-OUT DEFINITION
For quarter `q`, compare points scored within that quarter only unless provider defines cumulative quarter result. A+C, explicit rule ID.
### 2. REQUIRED INPUTS
Quarter-level pace/clock calibration, base injuries/weather; live quarter variants need current state TTL seconds. If rule semantics unknown, acquisition/engine blocks.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-12%; G5/FCS 10-15%. `b=1.8pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Quarter only; tie/draw/no-action by provider. Untimed down belongs to the quarter. OT never belongs to Q4 market unless explicitly defined otherwise.
### 5. VALIDATION PLAN
>=800 quarter observations pooled, but separate by quarter because behavior differs; >=125 challenger bets. Effective sample is game-clustered.
### 6. STATE TRANSITIONS
NO_ENGINE if quarter attribution not stored; INPUT_MISSING for live state loss; ENGINE_BLOCKED on rule mismatch; otherwise PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
Quarter result/scoring subcluster; repeated quarter tickets in one game are not independent.

## Quarter Spread
### 1. READ-OUT DEFINITION
Quarter-only margin PMF and exact cover/push predicate. A+C.
### 2. REQUIRED INPUTS
Quarter calibration + base/live inputs as above.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-12%; G5/FCS 10-15%. `b=1.8pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Quarter only, exact push, untimed downs included in their quarter.
### 5. VALIDATION PLAN
>=800 quarter spreads pooled, separate q1/q2/q3/q4 reliability and CLV.
### 6. STATE TRANSITIONS
PRICED only with quarter PMF; NO_ENGINE otherwise. Live state missing => INPUT_MISSING.
### 7. CORRELATION CLUSTER
Quarter result cluster; correlates with quarter ML/total and full-game paths.

## Quarter Total
### 1. READ-OUT DEFINITION
Quarter-only total points and over/push/under predicate. A+C.
### 2. REQUIRED INPUTS
Quarter pace/scoring calibration; end-of-half behavior specifically for Q2/Q4; live state where applicable.
### 3. HOLD AND THRESHOLD
NFL 6-10%; P4 8-12%; G5/FCS 10-15%. `b=1.8pp, lambda=0.70, z=1.50`.
### 4. SETTLEMENT RULES
Only points in named quarter; untimed downs included; no OT in Q4 unless explicit provider semantics.
### 5. VALIDATION PLAN
>=800 observations, separate quarter calibration; CLV to comparable close.
### 6. STATE TRANSITIONS
ENGINE_BLOCKED if clock/quarter attribution fails; otherwise PRICED then BET/PASS; INPUT_MISSING for live state gap.
### 7. CORRELATION CLUSTER
Quarter scoring + game scoring clusters.

## Alternate Spread
### 1. READ-OUT DEFINITION
Same discrete final margin PMF as spread, evaluated at every declared alternate line. No new simulation. A+C.
### 2. REQUIRED INPUTS
Core spread inputs plus paired prices for each alternate slot. Missing opposite price can make fair-price acquisition missing even though engine is PRICED.
### 3. HOLD AND THRESHOLD
NFL 8-15%; P4 10-18%; G5/FCS 12-25%, with long tails wider. `b=2.0pp, lambda=0.80, z=1.55`; hold and devig disagreement materially raise floor.
### 4. SETTLEMENT RULES
Same as full-game spread for each line, exact push where integer.
### 5. VALIDATION PLAN
>=1,000 settled alternate quote opportunities across price buckets; calibrate monotonicity across lines and probability buckets. Actual BET sample may take multiple seasons because thresholds are strict.
### 6. STATE TRANSITIONS
PRICED whenever core margin PMF exists; acquisition may be NOT_OFFERED per line. ENGINE_BLOCKED if alternate probabilities are not monotone. BET/PASS only for offered paired-price slots.
### 7. CORRELATION CLUSTER
`GAME_RESULT`; all alternates on same side are nearly the same position and cluster exposure must prevent ladder overbetting.

## Alternate Total
### 1. READ-OUT DEFINITION
Same total-score distribution evaluated at every alternate `L`; no new model. A+C.
### 2. REQUIRED INPUTS
Core total inputs + per-line paired prices.
### 3. HOLD AND THRESHOLD
NFL 8-15%; P4 10-18%; G5/FCS 12-25%. `b=2.0pp, lambda=0.80, z=1.55`.
### 4. SETTLEMENT RULES
Same as total; push exact integer.
### 5. VALIDATION PLAN
>=1,000 quote opportunities across line/price buckets; enforce monotone over probability as line increases. Multiple seasons likely for credible BET CLV on extreme alternates.
### 6. STATE TRANSITIONS
PRICED if total distribution exists; ENGINE_BLOCKED on monotonicity failure; BET/PASS only with valid paired quote.
### 7. CORRELATION CLUSTER
`GAME_SCORING`; alternate total ladders are one exposure, also correlated with team totals and offense props.

## Race to N Points
### 1. READ-OUT DEFINITION
Traverse scoring events in timestamp order on each path. `P(team S is first to reach >=N)`, with neither/tie state where market rules allow. A+C.
### 2. REQUIRED INPUTS
Drive scoring sequence, possession/clock, kickoff/field-position and special-teams scoring behavior. Base injuries/weather. N and exact market semantics required.
### 3. HOLD AND THRESHOLD
NFL 8-14%; P4 10-16%; G5/FCS 12-22%. `b=2.0pp, lambda=0.75, z=1.55`.
### 4. SETTLEMENT RULES
Use chronological scoring; defensive/ST scores count if market rules say any team points. OT can matter for high N under full-game rules. If neither reaches N, grade according to explicit no-winner/void option.
### 5. VALIDATION PLAN
>=600 settled race markets per N-band; many books offer only selective Ns, so credible sample may require 2+ seasons. Reliability and CLV to final same-N market.
### 6. STATE TRANSITIONS
NO_ENGINE if scoring-event order is not retained; INPUT_MISSING if market rule/N identity unknown; ENGINE_BLOCKED on score-sequence reconciliation failure; PRICED then BET/PASS.
### 7. CORRELATION CLUSTER
Game scoring + team offense clusters; race tickets at multiple Ns are highly redundant and must share one exposure cap.
