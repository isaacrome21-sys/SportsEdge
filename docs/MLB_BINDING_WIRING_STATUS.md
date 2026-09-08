# MLB binding wiring status

This branch intentionally does **not** claim 38/38 binding PASS.

Implemented:
- explicit `threshold_domain` contract with contradiction checks; no unknown-market inference;
- quote-origin identities preserved by normalization rather than manufactured by the model;
- orchestration-boundary validation before engine execution;
- binding failures return per-row `BLOCKED` through `run_candidate` rather than killing the slate;
- executable price, book, timestamp, event-instance, threshold, team and multi-pitcher guards;
- probability market/entity/period/source-market binding;
- recursive defense-in-depth scanner and omission/contradiction tests.

Still structurally blocked:
- upstream quote adapters must actually supply trusted `event_id` or `game_number` and canonical `team_id`/player identities where required;
- model readouts must emit explicit probability threshold/team identity for applicable markets;
- F5 moneyline 2-way tie-push versus 3-way semantics must be represented unambiguously before promotion;
- FIRST_HOME_RUN N-way including canonical NO_HOME_RUN requires an approved N-way devig path; multiplicative two-way devig is not approved;
- PITCHER_RECORD_WIN settlement remains scorer-decision semantics and must not be substituted with team result.

Until those source/readout contracts are populated and tested end-to-end, production eligibility remains fail-closed and no market should be promoted merely because unit tests pass.
