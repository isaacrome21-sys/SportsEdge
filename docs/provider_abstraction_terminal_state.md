# Provider abstraction terminal state

This branch is terminal for the bounded change when all of the following are true:

1. ESPN source and sportsbook identity are represented separately.
2. ESPN ML/RL/totals are eligible only with source-native freshness and declared 60-second routing TTL.
3. ESPN cannot synthesize or satisfy props, NRFI/YRFI, team totals, or additional derivatives.
4. Free-first game-market acquisition exists for non-frozen consumers and does not invoke a paid callback when eligible free quotes survive.
5. Exact-book requests fail closed unless the selected source's own payload establishes the requested book.
6. Consumer migration state and provenance are machine-readable and human-readable.
7. Spend attribution is explicitly PARTIALLY_PROVEN until durable quota/request observations exist; no retrospective cost is invented.
8. Future metered calls have a secret-free attribution writer available.
9. NFL 2026 frozen confirmation script/config/workflow are unchanged by this branch.
10. Hosted `market-provider-contract` CI passes on the exact PR head.

Items 1-9 are branch-content requirements. Item 10 is hosted evidence and cannot be claimed until GitHub Actions reports it green.
