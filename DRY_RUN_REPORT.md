# Dry-Run Report — Owner Receipt Infrastructure

**Date:** October 12, 2026 · **Branch:** `feat/receipt-infra-dryrun-20261012`
(base: integration head `265a701c4192c0632621a3d11a7a9e1f4a6910fa`)

## Status — read this first

This is **development verification only**. It exercises the owner
receipt format and the receipt-first safeguard on offline fixtures
inside sandbox archives. **Activation remains subject to Isaac's
separate approval**, under the Lane A HOLD: no activation, no
retrospective backfill, no holdout access, no production promotion
was performed or is implied by anything here. The freeze SHA is
chosen only at the moment an activation is separately approved;
none was preselected. No live capture was attempted; the
production archive (`archive/strict-forward-capture`) was never
written — its tree digest is asserted unchanged by the harness
itself, before and after every run.

## What was built

- `sportsedge/backtest/receipt_format.py` — the owner receipt
  format as an **extension of** (not a replacement for) the
  receipt-first safeguard. An envelope binds one immutable source
  payload (embedded byte-exact, `payload_sha256`-bound) to a
  fixture and participant identities, an **observation** instant,
  and a distinct **effective-availability** instant whose stated
  basis (`SOURCE_TIMESTAMP` / `FEED_PUBLICATION` /
  `OBSERVED_FIRST_SEEN`) caps how early availability may be
  asserted: payload-carried bases pin the effective time to the
  timestamp the payload itself carries; first-seen pins it to the
  observation instant. Missing effective time/basis, an effective
  time after observation, or a hash mismatch each fail closed.
  Corrections are append-only supersede references — a corrected
  fact is a new envelope; the original is never edited.
- `sportsedge/backtest/nfl_participation_receipt.py` — the NFL
  participation specialization. `kickoff_starters` and
  `snap_leaders` are distinct record types with disjoint required
  fields, so the two cannot be populated from each other: copying
  a snap-leader record into the starter field fails validation
  (`PARTICIPATION_SNAP_LEADER_AS_STARTER`), a starter without
  lineage evidence fails, and announcement evidence is refused
  as a starter source — announced starters live in their own
  list, labeled `ANNOUNCED`, never confirmed participation.
  Starter evidence must name its source class from the Item F
  hierarchy (GAMEBOOK / BOXSCORE_STARTER_RECORD / GAME_ACCOUNT).
- `sportsedge/backtest/receipt_dry_run.py` +
  `scripts/dry_run_receipt_infra.py` — the dry-run harness. Its
  sandbox guard refuses, before any write, the production archive
  path itself, anything containing/contained by it, anything
  inside the repository's `archive/` tree, and any directory not
  clearly named `dry-run`. There is no default archive path.

## What was exercised — the three scenarios

All scenarios run the real safeguard receipt layer, the real
frozen-input snapshot, the real v1 capture CLI and v2 wrapper,
and the real ACK outcome journal. The only fixtured seams are the
CLI's own documented offline seams (schedule getter, clock,
production pricer — the frozen pricer fail-closes offline by
design), the same seams the project's integration check uses.

**(a) ARCHIVED-in-sandbox — PASS (8/8 checks).** Owner receipt
issued over the capture input (effective availability
`2027-04-01T22:40:00Z`, basis `SOURCE_TIMESTAMP`, pinned to the
payload-carried quote timestamp); the wrapper drove the CLI to
CAPTURED; the archived record was located and verified by the
wrapper's own identity/provenance verification; the stored
ARCHIVED outcome carries the CLI's `elo_schedule_provenance`
byte-for-byte; the receipt preserves the input (and its quotes)
verbatim; the owner receipt re-validates from disk after the run.

**(b) REFUSED — PASS (6/6 checks).** A stale fixture (first pitch
already past at the run instant) refused in the real v1 CLI with
`AS_OF_NOT_PREGAME: capture instant is not before first pitch`,
before any pricing ran. The outcome is REFUSED, no evaluator
record was archived, and the quotes survive verbatim in the
receipt — a refusal stays a refusal, with its evidence preserved.

**(c) INDETERMINATE — PASS (10/10 checks).** Receipt issued and
snapshot frozen; a child process then wrote one complete
ARCHIVED outcome entry line into the sandbox journal and was
SIGKILLed before the ACK (real process death, the audit #2086
crash window). The receipt resolved to INDETERMINATE with the
ghost entry reported unacknowledged; reconciliation through the
real wrapper (which never ran the pipeline) superseded the
never-durable claim with a committed INDETERMINATE outcome
(reason `UNACKNOWLEDGED_OUTCOME_NOT_DURABLY_ESTABLISHED`), and the
ghost entry remains preserved in the journal.

## Tests

33 new tests, all offline: `tests/test_backtest_receipt_format.py`
(every validation rule, correction chains, write-once storage),
`tests/test_backtest_nfl_participation_receipt.py` (the
starter/snap-leader separation, both directions), and
`tests/test_backtest_receipt_dry_run.py` (the sandbox guard,
including attempts on the production tree that fail and write
nothing; the three scenarios; the CLI driver). Full-suite results
are reported with the branch; the integration baseline's single
known failure (the V2K numpy-environment preflight) is unchanged
and no new failures were introduced.
