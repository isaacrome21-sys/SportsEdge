# Free provider public-repo adoption boundary

SportsEdge uses the implementation pattern common in public sports-data projects: credential-free league/ESPN HTTP surfaces are isolated behind adapters, normalized into a stable internal quote shape, and kept separate from predictive model features.

This branch does not vendor or copy third-party source code. It reuses SportsEdge's already-merged ESPN scoreboard adapter and generalizes its fail-closed semantics into an internal provider contract.

Adopted patterns:
- provider adapter separated from model logic;
- normalized quote records;
- explicit source/book provenance;
- source-native freshness metadata;
- market capability declaration;
- unsupported markets fail closed rather than being synthesized;
- free-first routing for consumers that do not require a frozen transport;
- metered transport retained only when the requested contract cannot be satisfied freely.

The repository's existing ESPN adapter is the authoritative implementation basis for this branch. External public repositories are architectural references only; no external repository is treated as evidence for SportsEdge market observations.
