# NFL market-anchored residual research pricing (2026-10-11)

This is a pricing-layer challenger only. **Not forward CLV proof, not a
validated betting strategy, and never Model_P, Truth Gate, OFFICIAL or staking
authority.** No new paid odds calls and no historical model refit.

## Scope / preservation

- `scripts/run_nfl_lines_card.py`: current AUTO and issue card routes. Frozen
  Attempt-9 raw scores supply the independent margin and total, but their
  historical absolute-score isotonic calibration cannot create priced bets.
  A sidecar computes residual research rows only when a matching fresh,
  two-sided spread and total are present. Moneyline is optional but must also
  be paired if present. Without verified observed timestamp / kickoff, the
  sidecar is **NO_MODEL**.
- `scripts/render_auto_dk_phone_summary.py` and
  `scripts/render_nfl_myspari_card.py`: show only residual research leans
  with original DK quotes and explicit non-bet wording. Existing EV >= 2%,
  price >= -165, and forward track threshold remain required to surface a
  lean. No eligible bet markets were promoted.
- `scripts/run_nfl_unified_lines_card.py`: independent Attempt-9 residual
  sidecar on the existing frozen phone/prop engine. Frozen game-market
  betting remains disabled.
- `sportsedge/sports/nfl/residual_unified_adapter.py`: a generic sidecar
  for strictly prior Attempt-9, G1, or M2-style raw score means. It feeds
  residual-adjusted home and away means to the **existing frozen joint score
  simulation** without changing its shape, push handling or prop workload
  code. This is an opt-in research adapter; it is not a new promoted G1/M2.
- `sportsedge/nfl_run_it.py`: optional paired-quote residual research
  entry point, returning **no CardPick/bet rows**. The original scored
  RUN IT production path stays independent.
- No changes to `sportsedge/nfl_unified_phone.py`,
  `sportsedge/sports/nfl/unified_market_engine.py`,
  `sportsedge/sports/nfl/unified_run_it.py` or any frozen model/probability
  artifacts or locks.

## Pricing math

Predeclared conservative coefficients (NOT fitted): margin and total
`intercept=0, weight=0.10`, loaded from
`config/nfl_market_residual_research_v1.json`. For home margin `m`
and total `t`, the center is

`fair = market + intercept + weight * (independent_raw - market)`.

Home/away location = `((fair_total + fair_margin)/2,
(fair_total - fair_margin)/2)` and is rejected if outside frozen
score-grid mean bounds. The exact same frozen score distribution is
evaluated at the market-only anchor and residual-adjusted location.
A log-odds correction relative to that anchor is added to the **paired
POWER_V1 no-vig sportsbook** probability. Therefore an independent
raw score equal to the market center produces **zero additional edge**,
even when the frozen grid has nonzero tie/push/threshold skew.

`edge = conditional_residual_fair_p - paired_POWER_V1_no_vig_p`.
Full EV includes the actual integer-line push mass.

## Fail-closed controls / evidence

- Each supplied price pair must have an actual, non-finite-free opposite
  quote, valid lines, and provider timestamp no older than **600 seconds**.
- `as_of` must be before kickoff; undated or in-play/manual backfilled
  quotes do not earn residual prices.
- Total and spread are both required to identify a shared game-level
  location. A moneyline without an independent margin/total anchor cannot
  invent a moneyline fair price.
- No quote freshness floor, +2% edge reporting floor, -165 price cap,
  model freeze, or promotion rule was weakened.
- `forward_min_abs_adjustment_points = 0.5`; this is merely a
  preregistered threshold for tracking meaningful residual movements.
- Frozen Attempt-9 and 2021-24 discrete score shapes are **not**
  held-out residual evidence. Predeclared coefficients are not claimed to
  win. Any later coefficient fitting requires chronological season-based
  walk-forward testing and a separately initiated, fresh post-merge forward
  CLV window. `validated_markets` stays empty.

## Testing

Tests were committed **first** on the feature branch, before the helper.
Tests cover conservative shrinkage, zero-residual/zero-incremental-edge,
paired/finite/fresh quotes, prekickoff gate, integer-line push mass,
unchanged joint-score means, no bet authority, and AUTO suppression of
legacy inflated model probabilities.

