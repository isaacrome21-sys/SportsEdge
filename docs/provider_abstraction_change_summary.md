# Provider abstraction implementation summary

Implemented on `feat/free-provider-abstraction-20260915` from base `abaed7e4351f8579404dc725a4c736a0bff00ba8`.

- Added machine-readable provider capability/provenance contract.
- Added machine-readable consumer migration registry.
- Resolved ESPN/DraftKings identity: ESPN is transport; sportsbook is read from ESPN payload `provider.displayName`; fallback `ESPN partner` cannot satisfy exact-book requirements.
- Declared ESPN game-market routing TTL at 60 seconds with mandatory source-native timestamp.
- Added fail-closed provider admission and free-first routing.
- Added free MLB ML/RL/totals acquisition entrypoint and context-only CLI.
- Kept props, NRFI/YRFI, team totals and additional derivatives off ESPN substitution.
- Added redacted future metered-usage attribution writer; historical quota drain remains PARTIALLY_PROVEN.
- Added migration ledger, spend audit, terminal-state document, tests and hosted CI.
- Frozen NFL 2026 confirmation script/config/workflow are excluded and unchanged in branch diff.

No predictive or betting authority is granted by this change.
