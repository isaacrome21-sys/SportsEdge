# Build report — MLB first-inning PBP K/BTP complete-PA pool

**Starting main:** `d722da64cc984c4466bfb83457cc99d36f66c6e5`  
**Branch:** `feat/mlb-first-inning-pbp-strikeout-btp-pool-20261020`  
**State:** DRAFT / NOT VERIFIED / NO PROJECTION OR MARKET-TEST CLAIM.

## Built
The new complete-first-inning, gamePk/subject-bound historical plate-appearance pool computes:

* `PITCHER_K`: exact number of officially credited strikeouts thrown by a **confirmed first-inning starting pitcher** in the first half he pitched, counting only his completed PAs. A reliever/absent starter is not silently counted as a prior zero.
* `TEAM_BTP`: exact completed batter PA count in the chosen team's TOP or BOTTOM first inning, not inferred from opponent Ks, inning runs or pitch totals.

Requires both halves completely played, final completed official game, verified IDs and every first-inning completed PA, contiguous PA sequence, event identity, strikeout outcome flag, source hash, confirmed starter, game completion+observation strictly before target as-of, and minimum ten complete prior games. Source snapshots and completeness assertions **remain operator-supplied and unauthenticated by this code**; live StatsAPI event ingestion/manifest verification still must independently confirm them.

No calibrated probability distribution, runner, market pricing, odds, eligibility, frozen report or gate change. The existing M21 `FIRST_INNING_PITCHER_K_PBP_POOL_UNBUILT` and `FIRST_INNING_BATTERS_TO_PLATE_PBP_POOL_UNBUILT` canonical gates remain untouched until independently verified pool and chronological evaluation. Full-game/resume/correct-scoring revisions remain unproven.

## Exact code identities (Git blob SHA-1)
* `sportsedge/mlb_first_inning_pbp_pool.py`: `84d6445b23c72beecdf32cd3165b5443ecf60008`
* `tests/test_mlb_first_inning_pbp_pool.py`: `3af222ebe431836af02ae8de445616ade35526cd`
* `research/mlb_first_inning_pbp_pool_20261020/SCREEN_SPEC_DRAFT.md`: `e8b526898ab3754882d89150d43d820d459fd24d`

## Tests, screens, holds
11 parameterized synthetic test functions authored: credited K count, PA team half routing, future/duplicate games, missing subject start, invalid/omitted PAs, half sequence, impossible timestamp, insufficient source, fingerprint and M21 gate hold. **No passing test result independently claimed**; hosted CI + Rocky must verify exact head, derive checks from raw actual StatsAPI PBP, compare old-suite failure set to base.

The first-screen draft is `research/mlb_first_inning_pbp_pool_20261020/SCREEN_SPEC_DRAFT.md` (UNFROZEN, UNRUN). No actual 2025 PIT source manifest supplied and no paired historical DK K/BTP quotes certified. Verdict remains `INSUFFICIENT_DATA` / `NO_MARKET_TEST` without the evidence, never PLAY.

## Rocky handoff
Cross-check first-inning official scorer/source records, including pitcher changes and a strikeout overturned on review; ensure atBatIndex normalization is verified against independent original PBP and ten *actual starter* games, not coerced rows. Prove all gamePk, timestamps, PA counts and team halves match, and gate/registry/RUN IT sources are byte-identical. Keep draft; fresh CI on current main and explicit screen-data pins before any modeling gate review.
