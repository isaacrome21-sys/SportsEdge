# NBA props full-board prospective ledger adapter

Status: operational build; independent verification required.

This change closes the raw-to-priced record gap for the frozen NBA props
forward test. It prices every supplied PTS/REB/AST/PRA side through the existing
`NBA_PROP_EMPIRICAL_V1` phone adapter, then emits one durable prospective entry
record per complete event/player/market/line OVER/UNDER pair. Both `PICKED` and
`PASSED` records are retained. Blocked, stale, out-of-scope, post-tip,
single-sided, and wrong-slate rows remain visible in accounting and cannot enter
the ledger.

Safety properties:

- First countable slate is hard-bounded at 2026-10-21; no historical repricing.
- DraftKings, event id, capture id, timezone-aware capture/start timestamps, and
  complete same-capture pairs are required; nothing is guessed from names.
- Raw/priced rows are joined only by the pricer's documented one-for-one order,
  with side, line, price, family, player, distribution, and engine-stamp checks.
- One ledger row represents one pair, preventing OVER/UNDER from becoming
  duplicate independent rows under the evaluator's identity key.
- Push mass is preserved separately and OVER/UNDER model probabilities are
  conditioned on a non-push before entering the frozen two-sided evaluator.
- Every ledger row remains research-only, ineligible, non-promotable, and has no
  PLAY authority.

No frozen preregistration, engine, evaluator, shortlist threshold, registry,
grading, close-capture rule, or eligibility state is changed. This code does not
fetch DraftKings or write a production ledger automatically; the operator must
supply the captured board and point-in-time store to the CLI.

Verification command:

`python -m pytest tests/test_nba_full_board_ledger_20261021.py tests/test_nba_prop_engines_20261020.py tests/test_nba_props_forward_evaluator_20261020.py -q`

## Oct 21 causal/provenance hardening delta

Following code-path inspection of the draft, missing/empty sportsbook identifiers
no longer default to DraftKings. Only explicitly declared DK/draftkings book rows
can become ledger entries. Prospective times must satisfy the causal order
`quote_captured_at <= recorded_at < event_start` in absolute UTC.
Rows recorded before capture are separately accounted as
`RECORDED_BEFORE_CAPTURE` (`noncausal_rows`); tip-time or later records
remain `ENTRY_NOT_PRE_EVENT`. Five negative/boundary regression cases were
added, including missing/empty book, recorded-before-capture, equality at tip,
and equal capture/recording instants across different UTC offsets.

Exact changed blobs:
- `sportsedge/forward_validation/nba_full_board_ledger.py`:
  `3f66b51695870746086a92bfcb253ff11067ac3d`
- `tests/test_nba_full_board_ledger_20261021.py`:
  `754b919a96d3fa054d85948a7f4727d74c49eca0`

**New head requires fresh hosted CI and Rocky independent reproduction.**
Existing builder tests mentioned elsewhere in this PR predate this delta;
do not transfer their green claim to the new head. No new real capture or
forward-validation evidence was produced by this code change.

## Oct 21 hosted CI diagnostic and exact-head refusal-order repair

Hosted GitHub Actions on previous head `bd51ce890cde4b253bb5dcd34d044e7b5a07d4d9`
reported **9,051 passed, 1 failed, 5 skipped, 105 warnings, and 951 subtests passed**
in the `pytest-discovery` suite (180.38 s). The full `automation-core` job
failed on the same single test, while seven of nine visible workflow runs passed.

The exact failure was
`test_identity_book_slate_and_pre_event_fail_closed[quote_captured_at-2026-10-21T19:30:00-05:00-ENTRY_NOT_PRE_EVENT]`:
expected rejection `ENTRY_NOT_PRE_EVENT`, observed `RECORDED_BEFORE_CAPTURE`.
The prior implementation tested `recorded_at < captured_at` before
`captured_at >= event_start or recorded_at >= event_start`.

**Correction:** preserve all original fail-closed inequalities, but test the
late/at-tip condition first so the existing negative-control test identifies
an at-tip quote as `ENTRY_NOT_PRE_EVENT`; only strictly pre-event quotes
can be labeled `RECORDED_BEFORE_CAPTURE`. No prospective row is admitted
by this reorder that was formerly rejected. An existing pytest case covers
the exact precedence. No new tests, gating, engine or frozen spec changes.
The new revision needs hosted CI and Rocky's independent exact-head review;
do not transfer the previous 87-pass builder result or claim new tests passed.
