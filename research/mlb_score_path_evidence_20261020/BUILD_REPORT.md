# Build report — MLB M50 ordered-score path and bottom-ninth evidence

**Starting main:** `4d4a07cc9d06dfb71dcd5d4a23c780ce93875b12`  
**Branch:** `feat/mlb-ordered-scoring-postgame-evidence-20261020`  
**Scope:** source-labelled **POSTGAME OUTCOME EVIDENCE ONLY**. NOT a scoring-path probability model, NOT source-authenticated, no market pricing/eligibility.

A complete, ordered official-scoring event ledger plus an independent played-half-inning ledger is required to reconstruct raw settlement labels for races to 3/4/5/6/7 runs, first/last-run inning, first scoring play's run delta, highest team scoring inning, team with most won complete innings, whether home actually batted bottom ninth, and whether the game was tied after nine and reached extra innings. Explicitly **not** inferred from final score: a 3-3 *through nine* may finish 5-4 in extras, and a final result can never be treated as proof of a nine-inning tie. Raw tie classifications for highest/more won innings remain marked market-rule unresolved (no bookmaker terms pinned). Partial/unplayed bottom ninth is never recorded as an ordinary zero-run home half. Input must be official FINAL, complete run event count, valid correct team-by-half identity and scoring order, timestamps, source SHA shape, and exact run delta sum to actual reported final. A home team already leading after the top ninth must not bat the bottom half; extra innings require tie through nine. Every output keeps source verified=false, research=true, eligible=false, NO_MARKET_TEST.

**Limitation:** an asserted complete normalized scoring event ledger is **not** an independently authenticated raw StatsAPI PBP archive. Within-half chronological event ordering is taken as supplied. Grand slam STILL requires bases-state HR event attribution; scorer identity/review reversals must be source-audited separately. No prospective score-path construction or actual market odds, no event/fixture identity quotes. M50 canonical blockers stay unchanged and cannot be lifted from a postgame label factory.

## Files and exact Git blob SHA-1
* `sportsedge/mlb_ordered_score_path_evidence.py`: `502d6f1498c0f6a150361f89aed972669b2c8d0d`
* `tests/test_mlb_ordered_score_path_evidence.py`: `26ae4cfed75b88d5617a08cc8fbb63f4545c84a1`
* `research/mlb_score_path_evidence_20261020/SCREEN_SPEC_DRAFT.md`: `4e631fe06c4395de217822376323237dfc792972`

## Testing and screening
7 new synthetic pytest test functions, one heavily parameterized, authored for no-bottom-nine, ninth tie→extras with distinct final non-tie, impossible home ninth when already ahead, race ordering, run delta conservation, duplicate/omitted scoring plays and path source fingerprint. **Not independently green or historically scored as of authoring.** Proposed source/evaluation contract in `SCREEN_SPEC_DRAFT.md` is UNFROZEN/UNRUN; no rate, Brier/log loss, CLV, or EV claimed.

Rocky: independently hand-recompute from actual inning/event ledgers including a walkoff, 9th home skipped, tied after nine and completion in 10th, compare all 3–7 race rungs, and test same-inning event order cannot be deduced from inning totals. Confirm exactly no pricing authority and no governance/gates changed; compare full-suite errors with base. No promotion/merge without independent exact-head review.
