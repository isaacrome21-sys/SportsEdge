# CFB signal-quality hardening

This layer fixes the failure mode where a large CFB slate collapses to a few opaque bets without showing whether games were lost to model authority, stale context, price decay, benchmark conflict, public-heavy unconfirmed movement, or promo selection.

It does **not** loosen `CFB_TRUTH_GATE_V1` and it does **not** create `Model_P` from SP+, FPI, handles, news, weather, or promotions.

## Required separation

- `OFFICIAL`: genuine frozen SportsEdge `Model_P` + CFB Truth Gate pass.
- `MODEL_CANDIDATE`: genuine frozen SportsEdge `Model_P`, not promoted by Truth Gate.
- `HYBRID_CONTEXT`: non-model directional/context candidate. Never presented as Model_P.
- `PROMO_VALUE`: underlying non-model candidate whose payout is materially improved by a valid promotion. Promo does not change model authority.
- `WATCH`: candidate blocked or downgraded by stale/unknown required context, material benchmark disagreement, price decay, or public-heavy action without independent confirmation.
- `PASS`: no qualified basis to play.

## What now gets reason-coded

### Model authority

The current CFB registry remains fail-closed. `UNFROZEN` or `promotion_authority=false` forces OFFICIAL to zero even if a caller mistakenly supplies a probability or truth-gate flag.

### External benchmarks

SP+, FPI and market-implied expectations are diagnostics only. They are never votes and never create a probability. Material disagreement sends a non-model candidate to WATCH so it is visible rather than silently discarded.

### Price quality

The evaluator compares the current edge with the first eligible captured edge when those values exist. Losing at least half of the reference edge, or falling below the existing 3% CFB Truth Gate floor, emits `PRICE_DECAY`. Missed prices are never backfilled.

### Public betting / handles

The existing CFB thresholds are preserved: public-heavy means at least 70% tickets. Tickets/money alone do not create a directional signal. A public-heavy interpretation requires at least two independent non-capper source families. Capper/opinion sources have zero directional authority.

### Injury and weather freshness

Required injury and outdoor-weather inputs are freshness-gated. Stale or unknown required context becomes WATCH rather than assumed neutral. The evaluator only consumes captured data; it does not scrape or infer missing facts.

### Promotions

Boosts are applied after candidate selection. The system computes boosted break-even probability from the offered American price and boost percentage. Boosted EV may only be computed when a genuine `Model_P` exists. Otherwise the row remains `PROMO_VALUE`.

## RUN IT funnel

Every CFB run should print counts in this order:

`scanned -> model candidates -> price/context qualified -> Truth Gate eligible -> OFFICIAL`

The card should then expose CORE / SECONDARY / WATCH / PASS rows with reason codes. A legitimate run can still end at `0 OFFICIAL`; the point is to make the attrition visible and actionable.

## Frozen thresholds in this hardening layer

The policy file is `config/cfb_signal_quality_policy_v1.json`. It preserves the SportsEdge movement rules already in use:

- spread material move: >= 2 points or crossing key 3/7
- total material move: >= 1.5 points
- moneyline material move: >= 15 cents
- public-heavy threshold: >= 70% tickets

Freshness defaults are operational quality controls, not model weights: odds 15 minutes, handles 60, injuries 180, weather 120. They can be revised only by a policy change with tests; they do not alter the CFB Truth Gate.
