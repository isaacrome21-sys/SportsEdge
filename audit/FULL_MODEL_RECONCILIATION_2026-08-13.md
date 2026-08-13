# SportsEdge full-model reconciliation record — 2026-08-13

## Purpose
Reconcile the diverged GAME operational/context lane and NRFI/Pitcher-BB forward-shadow lane without rewriting or reordering evidence commits.

## Proven ancestry
- Common merge base: `fe64648be384c6e8b08d6c44df5ac4e1298d14a6` (`Archive immutable V5 pregame full-slate evidence`).
- Forward-shadow head used as reconciliation base: `14e27b8bcbed3a4b03f1dbe02abb30be97b2eed0`.
- GAME/context branch pre-reconciliation head: `2798f9f6dfe77eaef10b87a22cdab16a42d86db6`.
- Reconciliation branch: `full-model-reconcile-20260813`.

The reconciliation branch starts from the forward-shadow head so the existing NRFI V6 and Pitcher BB V6 protocol -> fit -> prediction history is not rebased or rewritten.

## Frozen forward-shadow evidence preserved
### NRFI/YRFI V6
- Candidate artifact SHA-256: `0bdf71e272e406611e241e2427904f3c8e3a9405700f440bedacf0b74ed1580e`.
- Scheduled evidence run: `31700854400`.
- Scheduled games: 9.
- Games predicted: 9.
- Prediction rows: 18 (YRFI + NRFI per game).
- Blocked games: 0.
- Prediction ledger SHA-256: `5a96adadc26ba365a93f37800eb36a4550e380c6c25a4f2196c93ce44c1912bd`.
- Outcomes attached at capture: false.
- Sportsbook data used by Model_P: false.

### Pitcher BB V6
- Candidate artifact SHA-256: `fa408d9a086f409e073ce811c93b1d47454a43d93cc08143038def793792a9cf`.
- Frozen Aug-12 serialized base-state SHA-256: `4867110378bce127f316005a7583eb8d213b213dc98a1145d1d9e2f5d0a6215f`.
- Aug-13 rolled runtime-state digest: `33f9088a8f3b4f0b48d4ab3321b16b6cd9a69ef429a1a57d7572e8128dc016c5`.
- Scheduled evidence run: `31700854400`.
- Probable starters predicted: 18.
- Prediction rows: 36 (Over + Under per starter).
- Blocked starters: 0.
- Prediction ledger SHA-256: `5872eed5ef9a91c86243db74af17ea373c43aa60f7ecf645d2d9d322cfb59e62`.
- Outcomes attached at capture: false.
- Sportsbook data used by Model_P: false.

## Lineup-projection preservation rule
The forward-shadow lane's current `sportsedge/mlb_lineup_projection.py` is part of the source logic that produced the Aug-13 forward evidence. It is not silently replaced by a different projection algorithm during reconciliation.

The currently evidenced forward-shadow projector uses:
- official MLB prior confirmed lineups only;
- current MLB active roster validation;
- deterministic recency-weighted slot assignment;
- no current-day outcomes;
- no sportsbook data;
- exact historical game IDs recorded as provenance.

Any future change to projection algorithm, lookback window, assignment method, or admissible source is versioned explicitly and cannot be back-applied to already captured evidence.

## V6 GAME context amendment
Catcher/weather/umpire/full-lineup/bullpen/arsenal context research is layered after the already-frozen prop evidence. It is a separate V6 GAME context lane and does not alter or relabel the NRFI V6 or Pitcher BB V6 candidates.

No V6 GAME context artifact is deployable until the literal feature contract, chronology-safe historical build, temporal selection/calibration, forward evaluation, live parity and artifact attestation all pass.

## Hits / Total Bases transport
Reconciliation adds a transport-only CI gate for the already-frozen fixtures. Deployment remains false until the exact gzip evidence is present and CI proves:

`gzip size/SHA -> gzip decompression -> canonical size/SHA -> untouched holdout -> exact-commit attestation`.

Locked values:

### Hits
- gzip size: 4,089,956 bytes
- gzip SHA-256: `84bc9bab6f36ff27b91bb23cd13429b677d58db429f3eb4b935f4354c96ca2dc`
- canonical size: 19,948,081 bytes
- canonical SHA-256: `aaa006155de8078057fae0bd764a6aebca7e06057d9e83669d816536c5471776`

### Total Bases
- gzip size: 7,305,084 bytes
- gzip SHA-256: `578f2c7e99c8615cb8f312b9b4ecbb3292db8b8a44d2155f6754d86710c23988`
- canonical size: 24,223,755 bytes
- canonical SHA-256: `1a816f5f46bf1042c2dcc13078092b6205b359a2ad49dca3fcfdb7b787914859`

## Deployment-authority rule
No manual boolean flip is accepted as deployment evidence. Future authoritative resolution must bind market eligibility to the exact artifact SHA, validation record and live/CI attestation evidence. Until that resolver is implemented and tested, existing separately attested production paths remain distinct from the generic fail-closed registry.
