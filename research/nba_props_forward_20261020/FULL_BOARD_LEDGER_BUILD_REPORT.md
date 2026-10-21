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
