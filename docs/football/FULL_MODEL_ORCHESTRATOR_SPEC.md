# SportsEdge Football Full-Model Orchestrator Spec

Status: implementation contract for NFL + CFB. The declared surface is `config/football_market_surface.json`.

## 1. Non-negotiable architecture

One game produces one shared Monte Carlo path set. There are no independent generative models for individual markets.

- **Engine A — drive/play simulator.** Simulates possession, drive state, down, distance, field position, score differential, time, personnel package, pace, play type, yards, turnovers, scoring, clock and terminal game state.
- **Engine B — participation/usage.** Chooses active players for every play and allocates snap share, route participation, target share, rush share, red-zone role, scramble share and game-script substitution. Blowouts must change participation rather than merely changing team efficiency.
- **Engine C — special teams/situational.** FG probability by distance/environment, XP/2PT decisions, punts/returns, kickoffs, onside behavior, kneels and end-of-half/end-of-game clock logic.

Every read-out is a deterministic extraction from those same paths. If QB1 has 287 simulated passing yards, the receiving/lateral attribution on those same plays must reconcile to that passing output under official-stat semantics. No market-specific hidden adjustment is allowed after simulation.

## 2. Simulator invariants

Each simulated path stores at minimum: game_id, simulation_id, drive_id, play_id, quarter, clock, possession, score_before/after, down, distance, yardline, play_type, passer, rusher, target, receiver, tacklers when modeled, yards by stat type, TD type, turnover type, special-teams result, penalty/no-play flag, personnel package, active-player set and substitution reason.

Hard reconciliation tests:

1. Team points equal the sum of scoring events under the chosen settlement rules.
2. Passing yards reconcile with completion/receiving attribution; sacks are not passing attempts.
3. Player rush attempts/yards reconcile with team rushing after kneel/stat-provider semantics.
4. Receiving targets >= receptions and receiving yards come only from completed credited passes.
5. Touchdown scorer markets use the same TD events that contribute to team/game scoring, with defensive and return TD types explicitly tagged.
6. Halves/quarters are slices of the full path, not re-simulations.
7. Alternate lines and race-to-N are predicates over the same path.
8. NFL margin PMF preserves discrete key-number mass, especially 3 and 7; no Gaussian smoothing across key numbers.

## 3. Key numbers and margin distribution

NFL spread pricing reads directly from the empirical simulated margin PMF `P(M=m)`, where `M=home_points-away_points`. For home spread `s`, cover probability is `P(M+s>0)`, push is `P(M+s=0)`. The simulator/calibration layer must preserve point mass at common football margins rather than fitting a continuous normal approximation. Half-point movement from -2.5 to -3 or -3 to -3.5 therefore changes fair probability by the actual simulated/calibrated mass at 3. The same applies at 7 and other discrete margins.

CFB uses a discrete PMF too, but its margin shape is much wider and more matchup-dependent. Extreme talent mismatches cannot share a single stationary variance assumption with conference games.

## 4. CFB mismatch / garbage-time regime

Engine A carries a latent competitive-state regime. When win probability and score/time state cross fitted garbage-time boundaries, pace, pass rate, defensive aggressiveness and explosive-play distributions transition toward garbage-time behavior. Engine B simultaneously increases substitution hazard for starters and re-allocates snaps to backups. The transition is probabilistic and fitted from historical substitutions/play calling, not a hard `lead >= X` switch.

For P4-vs-FCS and other extreme mismatches, starter player props are blocked unless participation/substitution distributions are identifiable. A correct team total can coexist with `INPUT_MISSING` on a star WR prop. Do not pretend the team mismatch uncertainty is the same thing as player usage certainty.

## 5. Injury and participation gate

NFL player-prop and player-dependent game pricing snapshots again after official inactives, normally around 90 minutes pre-kick. If a key player's active status or role remains unresolved, player markets dependent on that player return `INPUT_MISSING`; game markets may run `DEGRADED` only if the uncertainty is represented by a pre-declared mixture of participation states.

CFB reporting is materially less reliable. If QB1/QB2, lead RB, high-target receiver, kicker or other role-critical participation is unresolved and no defensible probability mixture exists, affected player markets are `INPUT_MISSING`. A game market may be `DEGRADED` only when uncertainty is explicitly modeled and uncertainty inflation propagates into the edge haircut. No silent "assume active" behavior.

## 6. Weather, surface and roof

Weather is forecast at kickoff, not observed-now. Wind is modeled vectorially where stadium orientation is available and at minimum by sustained speed + gust distribution. Passing efficiency, deep-target rate and FG make probability receive fitted wind effects. Temperature has smaller direct weight and mainly affects ball/field conditions; precipitation and surface affect footing, rush/pass efficiency and turnover distributions. Dome = outdoor weather disabled. Retractable roof requires confirmed/planned roof state; unresolved roof state uses a mixture or `INPUT_MISSING` for wind-sensitive kicker/longest-FG markets if the probability difference is material.

Suggested TTLs: weather forecast 60 min; roof decision 30 min once announced; NFL inactive/participation snapshot 10 min after official list; market quotes 30-90 sec; CFB depth/injury source 30-60 min on game day, with confidence metadata.

## 7. Full-model orchestration

`run full model` executes in this order:

1. Load the declared market surface from config. The provider response cannot define coverage.
2. Create one row per declared market slot (game + side/player/line variant as applicable) before acquisition.
3. Acquire raw paired prices and record `OFFERED`, `NOT_OFFERED(retry_eligible)`, `ACQUISITION_MISSING`, or `PROVIDER_UNSUPPORTED` independently.
4. Build a point-in-time input snapshot with lineage/TTL state.
5. Run Engine A once per game. Run Engine B/C as required, sharing the same path identity.
6. Apply every declared read-out to the same simulation paths.
7. For every priced offered slot execute the fixed decision sequence:
   `raw paired prices -> multiplicative/power/Shin devig -> devig-method disagreement uncertainty -> hierarchical model/market blend -> total uncertainty -> one haircut -> rank/multiple-comparison penalty -> conservative edge -> hold-aware floor -> uncertainty-adjusted Kelly -> hard per-bet cap -> correlation cluster gate -> BET/PASS`.
8. Emit the full grid, including markets that were not offered or not priceable.
9. Report correlation **clusters**, not raw ticket/candidate count.
10. `card_status=BETS_FOUND` iff >=1 final BET; otherwise `NO_BETS`.

## 8. Independent state layers

Never collapse these:

- Run: `READY | DEGRADED | BLOCKED`
- Acquisition: `OFFERED | NOT_OFFERED(+retry_eligible) | ACQUISITION_MISSING | PROVIDER_UNSUPPORTED`
- Engine: `PRICED | NO_ENGINE | INPUT_MISSING | ENGINE_BLOCKED`
- Decision: `BET | PASS`
- Card: `BETS_FOUND | NO_BETS`

`PASS` exists only when the market was actually priced and evaluated. `NO_ENGINE` can never render as `PASS`. `READY` is run health, never a betting decision.

## 9. Hold-aware floor

For a paired market, let the three devig methods produce fair probabilities `q_mult`, `q_power`, `q_shin`; let `sigma_devig` be their dispersion, `sigma_model` the model estimate SE, and `sigma_cal` calibration uncertainty. Let total standard error be

`SE_total = sqrt(sigma_model^2 + sigma_devig^2 + sigma_cal^2 + sigma_input^2)`.

Let observed two-way/market hold be `h`. Each market family defines a base floor `b_m` and a hold sensitivity `lambda_m`. The minimum conservative edge is

`floor_m(h,SE) = b_m + lambda_m * max(0, h-h_ref_m) + z_m * SE_total`.

The final conservative edge is computed only after one uncertainty haircut and multiple-comparison penalty. High hold therefore raises the floor; it never licenses weaker evidence. The card may apply a separate max-juice display/user filter, but engine value is defined without that filter.

## 10. Correlation exposure

A game has dense path clusters. Default top-level clusters:

- `GAME_RESULT`: ML, spread, alt spread, winning margin, largest lead.
- `GAME_SCORING`: total, team totals, alt totals, both-teams-to-N, total TDs.
- `HOME_OFFENSE`: home team total, home QB passing, home receivers, home rushers, home TD scorers.
- `AWAY_OFFENSE`: analogous.
- `QB_PASS_TREE:<team>`: attempts, completions, pass yards, pass TDs, INTs, receiver targets/receptions/yards/longest.
- `RUSH_TREE:<team>`: rush attempts/yards, QB rush, RB rush, rushing TDs.
- `TD_TREE:<team>`: team total TD, anytime/first/2+ TD tickets.
- `KICK_TREE:<team>`: scoring drives, FG made, longest FG, kicking points, XP.
- `DEFENSE_TREE:<team>`: sacks, pressure-linked QB outcomes, team turnovers, defensive TD.

Tickets sharing a cluster are one position with multiple claims on the same simulation path. Cluster exposure is capped after Kelly and per-bet caps. SGP pricing is not treated as independent-leg multiplication.

## 11. Dependency graph

```text
Point-in-time team + game inputs
        |
        v
Engine A: drive/play simulation
        |----> ML / spread / total / team total
        |----> halves / quarters / alternates
        |----> race-to-N / largest lead / margin bands / BTTS-N
        |----> team sacks / team turnovers (when play-event defense is modeled)
        |
        +------ Engine B: participation + usage
        |          |----> QB props
        |          |----> RB/WR/TE usage + yardage + volume props
        |          |----> player sacks/tackles/INT when defender participation model is available
        |          |----> TD scorer identity
        |
        +------ Engine C: special teams + situational
                   |----> FG/XP/kicking points/longest FG
                   |----> return TD / safety situational outcomes
                   |----> first score and TD scorer return components
```

## 12. Build order — cheapest first by information reuse

1. **A-path contract + reconciliation tests.** No market expansion before path integrity.
2. **Core game read-outs:** ML, spread, total, team total, halves, quarters, alternates. Nearly free once A exists.
3. **Path predicates:** race-to-N, margin band, largest lead, both-teams-to-N, total TDs.
4. **Engine B usage core:** snaps, routes, targets, rush share, QB participation; wire the new positional target-OE x offensive-usage matchup layer.
5. **High-volume QB/skill read-outs:** pass/rush/receiving yards, attempts, completions, receptions, rush attempts, targets.
6. **TD identity read-outs:** anytime/first/2+, only after score reconciliation + Engine B role model.
7. **Engine C:** FG/XP/kicking points/longest FG and special-teams score attribution.
8. **Defensive team read-outs:** sacks/turnovers.
9. **Defensive player props:** only after defender participation + stat-attribution quality is good enough.
10. **Thin/novel markets:** safety, first score variants, exotic longest props; these are last because hold and validation cost are high.

## 13. Markets that need more than the three engines

No listed market requires a separate *generative* model if Engines A/B/C contain the necessary event detail. However, **player tackles+assists** requires Engine B to include defensive-player participation and Engine A to assign tackle-credit distributions by play; **player sacks/interceptions** similarly require defender identity attribution. That is an extension of A/B, not an independent outcome model. If SportsEdge refuses to model defender identity, those markets must remain `NO_ENGINE` rather than use a detached prop model.

## 14. Validation reality under sample scarcity

Validation pools across games/players using hierarchical market models and walk-forward season splits; it does not pretend a single team's 17 NFL or ~12 CFB games are enough. Team-specific claims shrink strongly toward league/conference priors. New read-outs are challengers and do not inherit incumbent promotion.

For core NFL sides/totals, a full regular season yields only 272 game observations; one season is enough for a useful calibration/CLV read but not enough to establish small ROI differences. CFB has many more teams/games in aggregate, but distribution shift across conferences and talent bands makes raw sample count misleading. Player props generate more quote/settlement observations, yet observations share games/players and are strongly dependent; effective sample size is lower than ticket count.

Promotion prioritizes CLV and calibration (Brier, log loss, reliability) against a frozen incumbent. ROI remains descriptive only until a much larger sample exists.

## 15. Edge-likelihood ranking

This is an implementation priority ranking, not a promise of profitability.

1. **CFB niche player/usage markets when participation is actually known** — potentially most structural inefficiency, but often unavailable and frequently `INPUT_MISSING`.
2. **NFL/CFB player volume props (targets, attempts, rush attempts, receptions)** — usage/injury/news can create temporary mismatches; strong Engine B required.
3. **NFL/CFB yardage props** — positional matchup + usage interaction can add signal; still efficient in marquee games.
4. **Kicker/longest-FG and selected situational markets** — weather/decision modeling can matter, but holds are wider and samples slower.
5. **First-half/team-total derivatives** — some information reuse and lineup/weather sensitivity, but pricing is usually linked tightly to full-game markets.
6. **CFB G5/FCS sides/totals** — potentially less efficient, but thinner limits, stale/missing information and wider hold consume edge.
7. **CFB P4 sides/totals** — very competitive; model should PASS often.
8. **NFL team totals / derivatives** — sharp and highly correlated with the main market.
9. **NFL full-game sides/totals/moneyline** — among the sharpest prices in sports; PASS should be the normal output.
10. **Alternate lines / first TD / 2+ TD / exotic longshots** — widest hold and strongest selection/correlation pricing; model should almost always PASS unless the conservative edge is exceptional.

Full coverage means every declared slot has a truthful state, not that every family produces bets.
