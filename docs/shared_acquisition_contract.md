# SportsEdge Shared Acquisition Contract V1

Applies to MLB, CFB and NFL acquisition, RUN IT, hybrid review and automatic execution paths.

## Operating sequence

AUTO acquire everything available -> attach provenance/freshness -> isolate data gaps -> request only the smallest manual fill -> bind the fill under the same provenance/TTL rules -> continue the same run -> Model_P/distribution -> current no-vig market -> EV/Kelly/exposure -> execution gate.

Missing, stale or failed inputs are never zero-filled, inferred or silently replaced with league average values.

## Per-field provenance and quality

Every acquired datum must carry source name, source URI, observed/as-of timestamp when knowable, retrieved timestamp, freshness classification, confirmation status, trust class and source hash when available.

Freshness states are LIVE, RECENT, STALE, MISSING, SOURCE_FAILED and FRESHNESS_UNVERIFIED. Manual evidence is not exempt from TTL rules. A screenshot received now is not equivalent to a quote observed now unless the underlying observation time can be established.

Confirmation states distinguish official/verified facts from reported or unconfirmed information. Trust classes separate objective Model_P-eligible observations from context-only and market-only data. Stale, missing, failed or freshness-unverified observations may not remain MODEL_P_OBJECTIVE.

## Failure scoping

Failures are scoped to the narrowest affected object: field, player prop, market, game or genuinely shared dependency. A missing player-prop quote does not block unrelated markets or games. Partial RUN IT output is expected when unaffected markets remain evaluable.

## Weather hierarchy

Canonical objective weather acquisition remains authoritative public weather data, including NWS where supported by the sport adapter. MySportsWeather is an additional sports-specific corroboration/context layer and does not silently replace the canonical weather source. Disagreement must remain visible. Exact roof status and game-time weather vectors should be reacquired close to start time.

## Historical and rolling objective context

Adapters should maintain PIT-safe rolling and historical inputs required by Model_P, including appropriate 7/14/30-day, season-to-date and longer priors; usable handedness/platoon/home-road/opponent-quality splits; rest/travel/timezone/elevation effects; regressed park/venue effects; and official/validated umpire or referee tendencies when available.

MLB high-leverage objective context includes Statcast expected/contact metrics, pitch mix/velocity/whiff/chase, catcher framing/blocking/throwing, bullpen leverage/rest, defense/OAA-type metrics, park factors, lineups/starters/transactions and exact weather/roof context.

NFL/CFB high-leverage objective context includes depth charts, snaps/routes/targets/air yards/carries, pressure generated/allowed, coverage/run-fit splits, quantified coaching pace/play-call/red-zone/fourth-down tendencies, travel/short-week/altitude/dome effects and verified roster/injury changes. CFB additionally prioritizes measurable returning production, transfer impact and opponent-adjusted efficiency.

## Market-data hygiene

Acquire multi-book quotes with book identity and timestamps where available. Track opener/current movement, stale-quote state and CLV/steam metadata downstream. Market prices feed no-vig, EV, Kelly and execution logic only; they do not feed Model_P probability generation.

## Correlation and portfolio layer

Post-Model_P sizing must operate on the full slate and account for material correlations, including same-game player props, team total/game total relationships and shared environmental drivers. Exposure controls may reduce or reject individually positive-EV wagers when portfolio concentration is excessive.

## Delta update protocol

Late confirmed changes should trigger targeted reacquisition and rerun of affected dependencies rather than a mandatory full restart. Lineup, injury, depth-chart, weather/roof, umpire/referee and material market changes should produce a delta record showing old value, new value, source, timestamp and affected markets.

## Output hygiene

RUN IT output should distinguish evaluable from data-insufficient/do-not-price markets. For priced candidates, expose fair probability, no-vig market probability/price, edge, recommended stake or pass, the largest uncertainty driver and a compact provenance summary.

## Source priority

Prefer official or near-official feeds first: league APIs and official reports, Baseball Savant/Statcast, authoritative weather, official team/league injury and transaction sources, and reputable odds APIs. Community wrappers such as pybaseball, nflverse, CFBD or cfbfastR are acceptable when they improve reliability/completeness while preserving PIT provenance. Paid graded data is secondary unless it can be acquired cleanly, legally and timestamped.

## Governance

Social picks, handicapper opinions, public betting, ticket/handle percentages, sportsbook-derived probabilities, consensus projections and other market/opinion signals remain downstream context unless an underlying fact is independently verified from an objective source. They never become Model_P features or Truth Gate evidence merely because they were automatically acquired.
