# Shared Projection Integrity V1

This contract captures the cross-sport ideas worth adopting from public simulation/edge tooling without copying any proprietary projections or coefficients.

## Projection blending
A blended projection is allowed only from explicit components with source, version, as-of timestamp, value, and weights summing exactly to 1. The full blend definition is hashed so the weights cannot be silently changed after seeing a price or outcome.

This is intended for hierarchical/model blending, not for tuning a number to make a wager look attractive.

## Participation
Unresolved participation is not a soft downgrade. `QUESTIONABLE`, unknown, and equivalent unresolved states fail closed as `INPUT_MISSING_PARTICIPATION`. Only confirmed active/available states pass. Confirmed-out states are separately labeled `PARTICIPANT_OUT`.

## Correlation pricing
Parlay/SGP-style correlation is estimated from legs evaluated on the same simulation rows. Joint probability is measured directly from co-occurrence and is compared with the product of marginal probabilities. Multiplying standalone leg probabilities is not accepted as a correlated price.

## Simulation count
SportsEdge keeps a 50,000-simulation default for final probability work. Public tools commonly display 10,000 simulations, but that is not adopted as a design target.

## Evidence status
These utilities always emit `promotion_evidence: false`. Integration with a sport-specific runner remains `INTEGRATION_UNRUN` until the exact composed tree is executed against the frozen-fixture acceptance harness.
