# MLB Hitter Environment V1

## Purpose

Add a hitter-specific environment layer inspired by publicly described BallparkPal concepts without copying proprietary formulas or coefficients.

## Design

The model separates:

- stadium-only effects
- weather-only effects
- outcome-specific HR / XBH / single multipliers
- hitter spray profile: pull / center / opposite
- lineup aggregation using projected plate-appearance weights

The environment snapshot is point-in-time evidence and must include `as_of_utc` and `source`.

## Fail closed

Stale environment snapshots raise `ENVIRONMENT_SNAPSHOT_STALE`. The model does not silently replace stale/missing park or weather evidence with neutral 1.0 factors.

## No invented coefficients

SportsEdge does not embed BallparkPal coefficients. Directional stadium and weather factors must come from an independently sourced or empirically fitted table. Until those are validated, this module is plumbing only.

## Separation

`promotion_evidence` is always false. This module cannot make V6 eligible and cannot create an official bet by itself.

## Integration state

This PR is intentionally independent from the current divergent MLB branches. It remains `INTEGRATION_UNRUN` until the Sept 1 frozen-base composition test combines it with #96 and the pricing/execution layers.
