# NFL role-based prop challenger — 2026-09-21

Status: **research only**.

Authority footer: `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`

This challenger adapts the useful architecture observed in the supplied prop-model material without copying undisclosed coefficients or weights.

## Architecture

`point-in-time projected role + prior-game usage -> stabilized opportunity -> hash-bound football context -> one shared player simulation -> prop distribution -> paired quote -> POWER_V1 no-vig -> prop-only card/ledger`

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

## Point-in-time role stabilization

The card-facing entrypoint is `prepare_role_snapshot(...)` in `prop_research_lane.py`. It requires an explicit timezone-aware `as_of` strictly before kickoff. Every historical row and the projected-role row require `known_at <= as_of`.

Historical usage rows from the current game are rejected. Realized same-game fields such as actual/same-game snaps, snap share, routes, targets, carries, or other realized usage are rejected even when they are present in an input payload. This prevents a later box-score/snap feed from leaking into a pregame role estimate.

After that PIT filter, trailing usage is recency weighted and shrunk toward the pregame projected-role prior. Sparse histories and new roles are labeled `PROJECTED_ROLE` rather than treated as stable samples.

The probability lane is market blind. Sportsbook price, sportsbook line, market depth, and book agreement are rejected from role/context/efficiency inputs.

## Frozen context multipliers

Card-facing context is loaded only from the active versioned manifest:

`config/research/nfl_prop_role_context_manifest.json`

The manifest binds the active config path, version, and SHA-256. A byte change in the active multiplier config without a corresponding new version/manifest hash fails closed.

V1 intentionally exposes only a neutral multiplier profile while non-market context effects are still unfitted. The low-level `apply_context(...)` primitive remains available for isolated research, but it is not the governed card-facing path. Any future non-neutral multiplier set must be preregistered as a new version rather than tuned after observing prop outcomes.

## Shared simulation and correlated exposure

A single seeded simulation produces all player outcomes together. A shared latent pace factor moves pass, rush, and target opportunity in the same path. Passing, rushing, and receiving outcomes are generated from those opportunities and efficiency rates.

`RUSH_RECEIVING_YARDS` is literally the per-path sum of rushing and receiving yards. It is not priced by independently combining two marginal probabilities.

The simulation emits `estimate_p`; it does not emit `model_p`.

Bet rows are assigned an exposure group by `(game_id, player, component)`. Current components are:

- `USAGE`: attempts/completions/receptions
- `YARDAGE`: passing/rushing/receiving/rush+receiving yards
- `TD`: passing touchdowns
- `TURNOVER`: interceptions

Multiple edges produced by the same player/component simulation are displayed as separate contracts but count as **one independent exposure group**. For example, one player's rushing-yards, receiving-yards, and rush+receiving-yards rows are one `YARDAGE` exposure, not three independent bets.

## Separate prop card and ledger

Props never render through the NFL sides/totals `#896` card. This lane has its own schema:

`SPORTSEDGE_NFL_PROP_RESEARCH_CARD_V1`

and its own immutable research ledger namespace:

`ledger/nfl_prop_challenger/...`

The ledger records both every displayed contract and the unique exposure-group count. It carries literal zero authority and is not game-market evidence.

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
