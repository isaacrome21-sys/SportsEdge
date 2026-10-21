# Build report — NBA game-line evidence preflight (draft-only)

**Base main at creation:** `fe66963dbc15a6332648fde9adcb07ec560d31bf`  
**Branch:** `feat/nba-game-lines-forward-preflight-20261020`  
**Status:** DRAFT, UNSCORED, UNVALIDATED, no owner freeze, no forward clock, no eligibility or market state change.

## What was built, why it is not a verdict

New isolated `sportsedge.forward_validation.nba_game_lines_preflight.audit_nba_game_line_capture_preflight` accepts normalized, source-hash-bearing game-line quote pairs for exact DraftKings NBA MONEYLINE, SPREAD, TOTAL event identities. It reproduces the existing **DRAFT** forward-game-line prereg (unmerged branch `docs/nba-game-lines-forward-prereg-draft-20261020` @ `16e496569fe952bd6287cdce34479ae05a653650`, blob SHA1 `ee262c9ae5867f10042197b262620cd138d78c49`) §8 capture pair classification:

* Entry: mandatory two-sided SAME event/book/market/line capture, side receipt SHA shape, <=180-second quote age and <=150-second paired quote span, no post-tip entry counted.
* Close: final among supplied committed **pre-tip** captures, <=60-minute age, exact unchanged spread/total line. Stale, moved, post-tip, missing and single-sided close receives exactly the draft's named reason (`NO_CLOSE_ROW`, `LINE_MOVED`, `CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE`). The game-market moneyline single-sided close uses `LINE_MOVED`, per current draft. Ambiguous simultaneous last captures refuse rather than market-shop.
* Reject wrong sport/market identities, non-DraftKings source, duplicate capture IDs, invalid American odds, non-finite or non-halfpoint game lines, conflicting/pre-start clock. Source SHA is only **shape** evidence; a claimed fixture/quote digest is not independent authenticated DK proof.
* Output is ALWAYS `DRY_RUN_ONLY_PREREG_NOT_FROZEN`, `countable_prospective_rows: 0`, `verdict: NO_VERDICT_DRAFT`, no CLV/EV, no model-p fit, no PLAY, no suggestion any capture is independently verified. Unknown caller freeze/screen-pass fields are strictly refused (schema-only), rather than silently turning an unapproved row prospective.
* Does not change `sportsedge/forward_validation/core.py`, the frozen NBA PTS/REB/AST/PRA 2026-10-21 clock, Capture Spec V1, any runtime quote collector, model family state, owner rubric or frozen documents. This is **not a substitute** for the prereg's missing §3 candidate and historical §4 accuracy-pass evidence.

## Exact new files (Git blob SHA-1)

* `sportsedge/forward_validation/nba_game_lines_preflight.py`: `c4dac94726938b61e8d58df8e53067753e7e1236`.
* `tests/test_nba_game_lines_preflight.py`: `995a7b1336ec2300abb676d937351fc35c714f2f`.

20 synthetic pytest functions (some parameterized) authored, no independent passing execution yet. Must run exact-head unit and repo-wide suites and compare with base. Tests include five CLV missing reasons, exact 60-minute boundary, post-start refusal, noncontiguous/out-of-window quote pair, conflicting simultaneous closes, one-sided bookmaker, spoofed owner approval, duplicate records and zero countable results.

## Necessary evidence before NBA game-line validation can start

1. Owner-approved freeze of game-line prereg — this **DRAFT** may be amended, so this diagnostic must be re-reviewed against the FINAL hash and cannot unilaterally claim freeze.
2. Named candidate and independent *one-time* historical accuracy screen beating the §4 no-worse-than-market precondition on certified-price-vintage data, not the incumbent which previously failed.
3. Confirm actual fixture tipoff from independent event source, immutable DK entry and final pre-tip close quote receipts and permanent provenance. These normalized sample rows do not independently authenticate provider browser state.
4. Only **after** 1–3 can a different owner-frozen evaluator advance the countable clock, enforce sample floors, calculate CLV/Brier/bootstrap and produce a market verdict. No temporary research logic may preempt frozen market state.

## Rocky verifier handoff

Independently hand-score fixtures with last close at 60:00 vs 60:01, posttip-only closes, single-sided moneyline/total close, line moves, ambiguity and bogus source/market IDs. Confirm output cannot claim freeze even with user-injected flags. Check diff touches only two new files and this report; no bypass, no pricing, no capture behavior change. Require real exact-head hosted CI and failure-set equivalence. No merge or model/family promotion by builder.

## Builder correction on latest head

The builder found an adversarial schema edge before independent verification: a list/dict in `market` or a list in `quote.side` could otherwise raise an unhandled Python `TypeError`. This was corrected to the existing fail-closed codes `MARKET_OUT_OF_SCOPE` and `DUPLICATE_OR_UNKNOWN_QUOTE_SIDE`, with two additional synthetic test functions. No capture paths, model family statuses or frozen documents changed. Full current-head CI and the final PR diff must still be independently verified.
