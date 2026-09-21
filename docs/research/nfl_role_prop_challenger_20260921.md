# NFL role-based prop challenger — 2026-09-21

Status: **research only**.

Authority footer: `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`

This challenger adapts the useful architecture observed in the supplied prop-model material without copying undisclosed coefficients or weights.

## Architecture

`projected role + trailing usage -> stabilized opportunity -> football context -> one shared player simulation -> prop distribution -> paired quote -> POWER_V1 no-vig -> EV`

Supported families:

- pass attempts
- completions
- passing yards
- passing touchdowns
- interceptions
- rush attempts
- rushing yards
- receptions
- receiving yards
- rushing + receiving yards

## Role stabilization

Trailing usage is recency weighted and shrunk toward a pregame projected-role prior. Sparse histories and new roles are labeled `PROJECTED_ROLE` rather than treated as stable samples.

The probability lane is market blind. Sportsbook price, sportsbook line, market depth, and book agreement are rejected from role/context/efficiency inputs.

Football context is represented only through explicit preregisterable multipliers such as pass volume, rush volume, target opportunity, availability, opponent-efficiency adjustments, PROE/game-plan adjustments, and weather effects. Those multipliers are visible inputs, not a hidden composite score.

## Shared simulation

A single seeded simulation produces all player outcomes together. A shared latent pace factor moves pass, rush, and target opportunity in the same path. Passing, rushing, and receiving outcomes are generated from those opportunities and efficiency rates.

`RUSH_RECEIVING_YARDS` is literally the per-path sum of rushing and receiving yards. It is not priced by independently combining two marginal probabilities.

The simulation emits `estimate_p`; it does not emit `model_p`.

## Market layer

The quote evaluator requires:

- both Over and Under
- same sportsbook
- same line
- strict integer American prices
- `retrieved_at` on both sides
- quote age <= 180 seconds
- paired-side timestamp skew <= 30 seconds

The no-vig baseline uses `POWER_V1` through the shared EV math. The existing longshot sensitivity guard is retained: when the price range triggers the +400 check, disagreement among POWER/multiplicative/Shin beyond 1 percentage point blocks the evaluation.

Integer lines retain explicit push probability. EV is calculated as:

`win_p * (decimal_price - 1) - loss_p`

Push mass is refunded, not forced into win/loss. Probability edge compares the model's conditional non-push probability with the paired no-vig market probability.

## Diagnostics

Explanation tags such as `PROJECTED_ROLE`, `LOW_TRAILING_SAMPLE`, `HIGH_WIND`, `DEEP_MARKET`, and `THIN_MARKET` are deliberately separate from `estimate_p`.

There is no points score and no narrative `why` field that can alter ranking or probability.

## Governance boundary

This code does **not**:

- register a production NFL prop engine
- change `NO_ENGINE`/RUN IT authority
- create Model_P
- satisfy the Truth Gate
- grant promotion or staking authority
- backfill forward evidence
- create OFFICIAL bets

Chronological validation, calibration, minimum sample requirements, market pairing evidence, and promotion governance remain separate work.
