# MLB Context + Execution v1

Public research used for architecture, not copied proprietary formulas:

- Derek Carty / THE BAT X: daily context should include opponent, park, weather, umpire, catcher, bullpen, platoon, lineup position, surrounding-lineup quality, pitch counts and role. THE BAT park factors explicitly separate static park effects from weather.
- Eno Sarris / Stuff+, Location+, Pitching+: pitch quality is process-based. Stuff+ uses physical pitch characteristics such as velocity, movement, spin and release; Location+ evaluates location; Pitching+ combines process information and handedness context. These are treated as modest overlays until separately calibrated.
- Kevin Roth / WeatherEdge: weather effects are park-specific and use wind speed/direction, temperature and dewpoint; weather is not interchangeable with static park factor.
- UmpScorecards: useful public fields include accuracy above expected, consistency, favor and total run impact. Umpire context is capped so noisy single-ump effects cannot dominate a projection.
- Rufus Peabody / Captain Jack Andrews / Unabated: compare fair prices across books, price alternate/derivative lines, and measure CLV. Market price is part of decision quality, not an afterthought.
- Gadoon Kyrollos (Spanky): execution and limits matter. A theoretical edge at a quote that cannot be bet is not a tradable opportunity.
- Jonathan Bales: separate probability from payoff/EV; accuracy alone is not the objective.

## SportsEdge rules

1. Projection context and execution are separate layers.
2. Park and weather effects remain separate before combination.
3. Pitch-quality and umpire overlays are bounded until forward calibration exists.
4. A quote must be available and meet a minimum executable stake before it can pass the execution gate.
5. Best displayed price is not automatically best executable price.
6. All records from this module remain `promotion_evidence: false`.

## Not yet implemented

- calibrated weights for Stuff+/Location+/Pitching+ overlays
- empirical park-specific weather tables
- alternate-line distribution interpolation/general prop market consensus
- book-specific limit history/slippage model
- catcher framing integration

Those require data and forward validation; this contract intentionally fails short of claiming those pieces are proven.