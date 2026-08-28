# SportsEdge PGA model status

## Current-main foundation

The PGA lane is built around a joint field simulation rather than independent player probabilities.

Pre-event readouts from `sportsedge/pga_engine.py`:

- outright winner expected settlement share;
- first-round-leader expected settlement share;
- top-5 / top-10 / top-20 raw finish probability and dead-heat-adjusted expected payout share;
- make-cut probability using top-N-and-ties cut semantics;
- event head-to-head win/loss/push probability;
- common course-condition correlation, tee-wave correlation, persistent tournament-form correlation, player volatility, and right-tail blow-up risk;
- heavily regularized course-fit contribution.

Live readouts from `sportsedge/pga/`:

- actual leaderboard state is the simulation starting point;
- long-term skill remains the largest prior component;
- current-event T2G/ball striking can update the mean without replacing the prior;
- recent form, regularized course fit, putting/scrambling sustainability, weather/wave and volatility/error profile are bounded refinements;
- common conditions, wave shocks and persistent player form are jointly simulated;
- scoring changes are discrete so ties/dead heats remain real settlement outcomes;
- top-position EV uses expected paid fraction rather than treating every tied finish as a full win.

## Pricing and Truth Gate invariants

- American odds use the canonical SportsEdge validator.
- A partial outright/FRL field is never normalized to 100%; complete market coverage is required for N-way de-vig.
- Live card callers provide sportsbook price/no-vig market probability but cannot inject a model probability; the runner takes the probability from the simulation output.
- Point-in-time snapshots are immutable and hash-verified.
- Leaderboard, tee times, weather and market prices have independent freshness checks.
- WD status and market settlement rules must be verified.
- A market is blocked unless its quote is bound and that PGA market family is explicitly promoted.
- Code availability is not promotion evidence.

## Intentionally blocked / not claimed

- Live cut-event continuation is blocked until the live snapshot carries explicit cut state/rules. The runner will not guess them.
- The current weight values and variance parameters are model hypotheses, not a claim of out-of-sample superiority.
- No PGA market family is promoted merely by merging this implementation.
- Predictive promotion requires point-in-time historical/forward evidence by market family, with calibration and settlement semantics verified before official betting eligibility.
