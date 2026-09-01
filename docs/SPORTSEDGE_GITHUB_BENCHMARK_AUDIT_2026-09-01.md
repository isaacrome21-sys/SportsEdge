# SportsEdge MLB / CFB / NFL GitHub benchmark audit — 2026-09-01

SportsEdge was compared with mature public sports-data stacks including nflverse/nflreadr+nflfastR, sportsdataverse/cfbfastR, and jldbc/pybaseball. The goal is to adopt stronger acquisition, identity, caching, schema, provenance, speed, and historical-feature practices without importing market-derived projections into Model_P.

## Highest-value findings

- NFL: expand PIT-safe use of nflverse from schedule/depth charts toward official/fresh injury evidence, snap counts, weekly stats, advanced PBP and participation where actually available. nflfastR EPA/WP/CP remain benchmark/context unless separately validated.
- CFB: use prebuilt historical loaders, explicit ID crosswalks, rosters/participants, returning production, recruiting/talent priors and strictly-prior coaching/usage features. External ratings remain context unless certified.
- MLB: make pitch-level Statcast rolling windows first-class, hash raw snapshots because historical Statcast can revise, and cache/parallelize bounded history pulls. Never persist empty current/future responses as successful evidence.

## Cross-sport P0 controls

1. Typed provider capability registry: sport, domain, priority, trust class, TTL, required schema, live/history support, fallback relationships.
2. Schema drift fingerprints before normalization.
3. Content-addressed historical cache discipline with negative-live-cache protection.
4. Concurrent independent-domain fanout while same-domain fallbacks remain ordered.
5. Explicit entity crosswalks; no fuzzy predictive joins.
6. Source revision awareness and immutable acquisition hashes.
7. Incremental local feature store for repeated RUN IT speed.
8. Reference-model benchmark lane isolated from incumbent Model_P.

## Governance

Raw objective facts may become candidate Model_P inputs only with PIT timestamps, resolved identity, provenance and forward validation. Market prices, public betting, consensus projections and external betting/model outputs do not become Model_P inputs merely because a public package exposes them. A context-only fallback can never silently satisfy a Model_P-objective requirement.

The accompanying `sportsedge.provider_resilience` module implements provider specs, deterministic primary/fallback planning, required-field schema validation, schema fingerprints, manifest hashing, Model_P trust checks, negative-live-cache protection, and independent-domain parallel planning. It changes no Model_P coefficients, Monte Carlo math, Truth Gate thresholds or promotion state.
