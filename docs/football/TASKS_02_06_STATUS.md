# Football roadmap tasks 2-6 status

## Task 2 — SportAdapter protocol

**Status: COMPLETE.** Shared `SportAdapter` protocol exists under `sportsedge/core/`, with NFL and CFB adapters. With no data ingestor configured they fail closed with `NotImplementedError`, preserving the task-2 acceptance contract. When an ingestor is injected, schedule/history calls route through it.

## Task 3 — NFL lines-history ingestion

**Status: CORE IMPLEMENTED; PARQUET MATERIALIZATION BLOCKED BY DEPENDENCY POLICY.**

Implemented:
- nflverse schedule CSV source contract
- CSV parsing and season filtering
- numeric normalization for line/price columns
- row-count and null-rate reporting helpers by era
- injectable `.parquet` writer boundary

Not done yet: writing a real parquet file in CI. Current CI installs only `numpy`; `FOOTBALL_ROADMAP.md` says not to add dependencies without approval. A real parquet writer requires an approved dependency such as `pyarrow`/`pandas` or an existing repo-native writer. Until approved, `ingest()` fails closed with `PARQUET_WRITER_NOT_CONFIGURED` rather than writing a fake parquet file.

## Task 4 — CFB lines-history ingestion

**Status: CORE IMPLEMENTED; LIVE CACHE MATERIALIZATION PENDING.**

Implemented:
- bulk-by-season ingestion, never per game
- `games` + `lines` endpoint plan
- hard API call budget
- 2013-2025 plan consumes 26 calls, well below the <=100 acceptance ceiling
- injectable parquet writer boundary

A live CFBD cache still needs credentials/transport plus an approved parquet writer. The code does not fabricate either.

## Task 5 — leakage assertion harness

**Status: COMPLETE.** `assert_feature_asof_before_game()` enforces strict `feature_asof_ts < game_start_ts` and the deliberately leaked equal-timestamp fixture is rejected.

## Task 6 — joint score simulator with key-number mixture

**Status: ENGINE COMPLETE; FULL EMPIRICAL ATTESTATION PENDING TASK-3 CACHE.**

Implemented:
- discrete integer margin PMF
- explicit absolute empirical point mass at key margins (including +/-3 and +/-7)
- remaining mass allocated from a discretized normal
- internally consistent nonnegative integer home/away scores
- deterministic seeded Monte Carlo
- tests verify PMF normalization and exact preservation of injected empirical key masses

The final acceptance check — comparing the simulator to the full empirical NFL margin PMF from the historical cache — should be run only after task 3 materializes the canonical history cache. This avoids embedding guessed key-number frequencies.

## Verification

PR #79 automation-core CI passed: **277 tests, 0 failures**. The new football tests covering tasks 2-6 all passed.

## M2 market-leak audit

GitHub code search did not return an indexed `M2` implementation to audit. That is **not** treated as proof that M2 is clean. When the football M2 feature module is introduced in tasks 12/13, its contract must explicitly prohibit line, total, implied probability, price, and book-derived fields and add a recursive banned-market-field test similar to the existing V7 baseball contract.
