## Scope
Generalize SportsEdge's existing free ESPN game-odds fallback into an explicit provider capability/provenance contract for non-frozen consumers.

## Implemented
- separates transport (`ESPN_SCOREBOARD`) from sportsbook identity (`provider.displayName` from the ESPN payload);
- exact-book admission succeeds only when the selected source's own payload names the required book;
- declares ESPN capability as MLB ML/RL/totals only and refuses props, NRFI/YRFI, team totals and additional derivatives;
- declares source-native timestamp requirement and 60-second routing TTL;
- adds free-first provider routing and a free MLB game-market context entrypoint/CLI;
- adds machine-readable consumer migration registry plus human-readable migration ledger;
- adds redacted future metered-usage attribution; historical quota exhaustion remains PARTIALLY_PROVEN rather than guessed;
- adds exact-head hosted CI for provider contract, migration scope and frozen-file exclusion.

## Frozen exclusion
No changes to `scripts/nfl_2026_line_capture.py`, `config/nfl_2026_capture.json`, or `.github/workflows/nfl-2026-line-capture.yml`.

## Authority
Routing/provenance only. No Model_P, promotion, Truth Gate, eligibility, staking, or OFFICIAL authority changes.

## Terminal gate
Do not merge until `market-provider-contract` is green on the exact PR head.
