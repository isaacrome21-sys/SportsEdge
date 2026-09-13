# MLB Prop Distributions v1

Purpose: convert structural MLB projections into market-specific probabilities after candidate discovery and before market-consensus/EV gating.

## Environment channels
Environment is not a single score. It is represented as separate multiplicative effects for:
- HR
- XBH
- Runs
- Strikeouts

This lets the same park/weather setup affect home-run, total-base, hits-allowed, and strikeout markets differently.

## Initial transparent distributions
- hitter 1+ hit: Bernoulli approximation across effective projected PA
- pitcher strikeouts: Poisson count from projected BF × K rate × K environment
- pitcher hits allowed: Poisson count from projected BF × xBA allowed × contact environment
- total bases: Poisson approximation from per-PA TB × projected PA with XBH/HR environment weighting
- recorded outs: structural expectation from projected BF and non-out rate

These are intentionally simple v1 pricing distributions. They must be validated/calibrated before any thresholds are promoted or treated as production truth.

## Pipeline separation
Candidate Finder -> Distribution -> Market Consensus -> Offered-price EV -> Truth Gate.

Every distribution result has `promotion_evidence: false`. This layer does not alter V6 eligibility, frozen holdout evidence, or promotion gates.
