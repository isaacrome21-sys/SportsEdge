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

## Frozen benchmark methodology

`config/pga_benchmark_methodology.json` is the validation benchmark contract and is enforced by the cross-sport market-coverage CI gate.

- `OUTRIGHT` and `FIRST_ROUND_LEADER` are exhaustive mutually-exclusive N-way fields and use `MULTIPLICATIVE_NWAY_V1`. The complete field is mandatory; partial-field normalization is blocked.
- `TOP_K` is **not** an N-way winner market because multiple golfers can cash simultaneously. It is benchmarked as a binary proposition per golfer and requires paired YES/NO prices. Cross-player normalization is forbidden. Settlement evaluation uses dead-heat-adjusted expected paid fraction.
- `MAKE_CUT` is likewise binary per golfer, requires paired YES/NO prices, and cannot be normalized across golfers.
- `H2H` uses paired two-way de-vig; pushes are tracked separately rather than coerced into a binary win/loss outcome.
- Every benchmark observation produced by `sportsedge.pga.benchmark` records the methodology and an SHA-256 of the quote set. A methodology mismatch is fail-closed and promotion does not transfer across market shapes.

This contract is frozen before PGA predictive replay/forward evidence exists. No historical evidence collected under a different market-shape methodology can be used for promotion without an explicit versioned migration/re-run.

## Intentionally blocked / not claimed

- Live cut-event continuation is blocked until the live snapshot carries explicit cut state/rules. The runner will not guess them.
- The current weight values and variance parameters are model hypotheses, not a claim of out-of-sample superiority.
- No PGA market family is promoted merely by merging this implementation.
- Predictive promotion requires point-in-time historical/forward evidence by market family, with calibration and settlement semantics verified before official betting eligibility.
