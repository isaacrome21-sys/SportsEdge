# Provider abstraction review checklist

- [ ] `market-provider-contract` hosted CI green on exact head.
- [x] ESPN transport identity separated from sportsbook identity.
- [x] Exact-book admission requires source payload sportsbook match.
- [x] ESPN ML/RL/totals only; props/NRFI/YRFI/team totals/derivatives do not silently substitute.
- [x] ESPN routing TTL declared at 60s and source-native timestamp required.
- [x] Free-first entrypoint does not call paid provider when eligible free quotes survive.
- [x] Consumer migration registry and human-readable ledger included.
- [x] Historical spend attribution remains PARTIALLY_PROVEN; no invented request counts.
- [x] Future metered usage attribution can record observed quota deltas without credentials.
- [x] Frozen NFL confirmation script/config/workflow absent from branch diff.
- [x] No Model_P, promotion, Truth Gate, staking, eligibility, or OFFICIAL authority granted.
